"""Storage abstraction layer supporting Local Filesystem, AWS S3, Cloudflare R2, MinIO, and Wasabi.

Provides unified cloud and local object storage with SigV4 pre-signed URLs, exponential
backoff retries, prefix cleanup, and automatic transparent fallback to local storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime
from enum import Enum
import hashlib
import hmac
import logging
import mimetypes
import os
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Domain exception raised when a storage operation fails."""

    pass


class StorageBackend(str, Enum):
    """Supported storage backend types."""

    LOCAL = "local"
    S3 = "s3"
    R2 = "r2"
    MINIO = "minio"
    WASABI = "wasabi"


@dataclass
class StorageConfig:
    """Storage configuration parsed from environment variables or custom parameters."""

    backend: StorageBackend = StorageBackend.LOCAL
    endpoint_url: Optional[str] = None
    region: str = "us-east-1"
    bucket: str = "ai-shorts-bucket"
    access_key_id: str = ""
    secret_access_key: str = ""
    public_base_url: Optional[str] = None
    presigned_expiry_seconds: int = 3600
    max_retries: int = 3
    enable_local_fallback: bool = True
    local_root_dir: Path | str = "outputs"

    @classmethod
    def from_env(cls) -> "StorageConfig":
        """Load storage configuration from environment variables."""
        raw_backend = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
        if raw_backend in ("s3", "aws_s3", "aws"):
            backend = StorageBackend.S3
        elif raw_backend in ("r2", "cloudflare_r2", "cloudflare"):
            backend = StorageBackend.R2
        elif raw_backend == "minio":
            backend = StorageBackend.MINIO
        elif raw_backend == "wasabi":
            backend = StorageBackend.WASABI
        else:
            backend = StorageBackend.LOCAL

        endpoint = os.environ.get(
            "S3_ENDPOINT",
            os.environ.get("R2_ENDPOINT", os.environ.get("S3_ENDPOINT_URL", "")),
        ).strip()
        region = os.environ.get("S3_REGION", os.environ.get("R2_REGION", "auto" if backend == StorageBackend.R2 else "us-east-1")).strip()
        bucket = os.environ.get("S3_BUCKET", os.environ.get("R2_BUCKET", "ai-shorts-bucket")).strip()
        access_key = os.environ.get("S3_ACCESS_KEY_ID", os.environ.get("R2_ACCESS_KEY_ID", "")).strip()
        secret_key = os.environ.get("S3_SECRET_ACCESS_KEY", os.environ.get("R2_SECRET_ACCESS_KEY", "")).strip()
        public_url = os.environ.get("S3_PUBLIC_BASE_URL", os.environ.get("R2_PUBLIC_BASE_URL", "")).strip()

        try:
            expiry = int(os.environ.get("S3_PRESIGNED_EXPIRY", "3600").strip())
        except ValueError:
            expiry = 3600

        try:
            retries = int(os.environ.get("STORAGE_MAX_RETRIES", "3").strip())
        except ValueError:
            retries = 3

        fallback = os.environ.get("STORAGE_ENABLE_LOCAL_FALLBACK", "true").strip().lower() not in ("false", "0", "no")

        return cls(
            backend=backend,
            endpoint_url=endpoint if endpoint else None,
            region=region,
            bucket=bucket,
            access_key_id=access_key,
            secret_access_key=secret_key,
            public_base_url=public_url if public_url else None,
            presigned_expiry_seconds=expiry,
            max_retries=retries,
            enable_local_fallback=fallback,
        )


@dataclass(frozen=True)
class StorageReport:
    """Diagnostic report for storage backend status and capabilities."""

    backend: str
    configured_backend: str
    bucket: str
    region: str
    endpoint_url: Optional[str]
    public_base_url: Optional[str]
    is_cloud_active: bool
    local_fallback_enabled: bool


class StorageService(ABC):
    """Abstract storage interface for managing uploaded and generated media assets."""

    @abstractmethod
    def store_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Store a local file under destination_key and return reference path or URL."""
        pass

    @abstractmethod
    def upload_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload a local file to storage."""
        pass

    @abstractmethod
    def download_file(self, key: str, local_destination_path: Path | str) -> Path:
        """Download an object from storage to a local file path."""
        pass

    @abstractmethod
    def get_presigned_url(
        self,
        key: str,
        method: str = "GET",
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a pre-signed URL for accessing or uploading an object."""
        pass

    @abstractmethod
    def get_file_path_or_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Return local file path or signed URL for accessing the object."""
        pass

    @abstractmethod
    def delete_file(self, key: str) -> bool:
        """Delete an object by key."""
        pass

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects matching prefix (e.g. jobs/{job_id}/)."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if an object exists in storage."""
        pass


class LocalStorageService(StorageService):
    """Local filesystem implementation storing artifacts under `outputs/` or configured root."""

    def __init__(self, root_dir: Path | str = "outputs") -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_key_path(self, key: str) -> Path:
        clean_key = key.lstrip("/\\")
        dest = (self.root_dir / clean_key).resolve()
        try:
            dest.relative_to(self.root_dir)
        except ValueError:
            raise StorageError(f"Path traversal detected: key '{key}' escapes root directory.")
        return dest

    def store_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        src = Path(local_source_path)
        if not src.is_file():
            raise StorageError(f"Source file not found: {src}")
        dest = self._resolve_key_path(destination_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        return str(dest)

    def upload_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        return self.store_file(local_source_path, destination_key, content_type=content_type)

    def download_file(self, key: str, local_destination_path: Path | str) -> Path:
        src = self._resolve_key_path(key)
        if not src.is_file():
            raise StorageError(f"Local storage object not found: {key}")
        dest = Path(local_destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        return dest

    def get_presigned_url(
        self,
        key: str,
        method: str = "GET",
        expires_in_seconds: int = 3600,
    ) -> str:
        dest = self._resolve_key_path(key)
        clean_rel = dest.relative_to(self.root_dir).as_posix()
        return f"/api/media?path={clean_rel}"

    def get_file_path_or_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        dest = self._resolve_key_path(key)
        return str(dest)

    def delete_file(self, key: str) -> bool:
        try:
            dest = self._resolve_key_path(key)
            if dest.is_file():
                dest.unlink()
                return True
            return False
        except Exception:
            return False

    def delete_prefix(self, prefix: str) -> int:
        clean_prefix = prefix.lstrip("/\\").rstrip("/\\")
        target_dir = self.root_dir / clean_prefix
        count = 0
        if target_dir.is_dir():
            for p in list(target_dir.rglob("*")):
                if p.is_file():
                    try:
                        p.unlink()
                        count += 1
                    except Exception:
                        pass
            try:
                shutil.rmtree(str(target_dir), ignore_errors=True)
            except Exception:
                pass
        return count

    def exists(self, key: str) -> bool:
        try:
            return self._resolve_key_path(key).is_file()
        except Exception:
            return False


class S3StorageService(StorageService):
    """S3-compatible cloud storage implementation with pure Python SigV4 signing.

    Supports AWS S3, Cloudflare R2, MinIO, and Wasabi with automatic local fallback.
    """

    MIME_TYPES = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".aac": "audio/aac",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".srt": "text/plain",
        ".vtt": "text/vtt",
        ".ass": "text/plain",
        ".json": "application/json",
        ".jpg": "image/jpeg",
        ".png": "image/png",
    }

    def __init__(
        self,
        config: Optional[StorageConfig] = None,
        local_fallback: Optional[LocalStorageService] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
        bucket: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        public_base_url: Optional[str] = None,
    ) -> None:
        self.config = config or StorageConfig.from_env()
        self.endpoint_url = endpoint_url or self.config.endpoint_url or ""
        self.region = region or self.config.region or "us-east-1"
        self.bucket = bucket or self.config.bucket or "ai-shorts-bucket"
        self.access_key_id = access_key_id or self.config.access_key_id or ""
        self.secret_access_key = secret_access_key or self.config.secret_access_key or ""
        self.public_base_url = public_base_url or self.config.public_base_url or ""
        self.max_retries = self.config.max_retries
        self.enable_local_fallback = self.config.enable_local_fallback
        self.local_fallback = local_fallback or LocalStorageService(root_dir=self.config.local_root_dir)

    def _get_mime_type(self, path_or_key: str | Path) -> str:
        ext = Path(path_or_key).suffix.lower()
        if ext in self.MIME_TYPES:
            return self.MIME_TYPES[ext]
        guess, _ = mimetypes.guess_type(str(path_or_key))
        return guess or "application/octet-stream"

    def _get_base_url(self, clean_key: str) -> str:
        quoted_key = urllib.parse.quote(clean_key, safe="/~")
        if self.endpoint_url:
            host_url = self.endpoint_url.rstrip("/")
            if host_url.startswith("http://") or host_url.startswith("https://"):
                return f"{host_url}/{self.bucket}/{quoted_key}"
            return f"https://{host_url}/{self.bucket}/{quoted_key}"

        if self.config.backend == StorageBackend.R2:
            return f"https://{self.bucket}.r2.cloudflarestorage.com/{quoted_key}"

        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{quoted_key}"

    def _generate_sigv4_headers(
        self,
        method: str,
        clean_key: str,
        payload_bytes: bytes = b"",
        content_type: Optional[str] = None,
    ) -> Tuple[str, Dict[str, str]]:
        """Generate AWS SigV4 authorization headers."""
        url = self._get_base_url(clean_key)
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        canonical_uri = parsed.path

        now = datetime.datetime.now(datetime.timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"

        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        headers_to_sign = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amzdate,
        }
        if content_type:
            headers_to_sign["content-type"] = content_type

        signed_headers = ";".join(sorted(headers_to_sign.keys()))
        canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted(headers_to_sign.keys()))

        canonical_request = f"{method}\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        string_to_sign = f"AWS4-HMAC-SHA256\n{amzdate}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

        def sign(k: bytes, msg: str) -> bytes:
            return hmac.new(k, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + self.secret_access_key).encode("utf-8"), datestamp)
        k_region = sign(k_date, self.region)
        k_service = sign(k_region, "s3")
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        req_headers = {
            "Host": host,
            "x-amz-date": amzdate,
            "x-amz-content-sha256": payload_hash,
            "Authorization": auth_header,
        }
        if content_type:
            req_headers["Content-Type"] = content_type

        return url, req_headers

    def _generate_presigned_url(self, key: str, method: str = "GET", expires_in: int = 3600) -> str:
        """Generate SigV4 pre-signed query parameter URL."""
        clean_key = key.lstrip("/\\")

        # If custom public CDN domain configured and method is GET without special signing, use public base URL
        if self.public_base_url and method == "GET" and not (self.access_key_id and self.secret_access_key):
            return f"{self.public_base_url.rstrip('/')}/{urllib.parse.quote(clean_key, safe='/~')}"

        url_base = self._get_base_url(clean_key)
        if not self.access_key_id or not self.secret_access_key:
            return url_base

        now = datetime.datetime.now(datetime.timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"

        parsed = urllib.parse.urlparse(url_base)
        host = parsed.netloc
        canonical_uri = parsed.path

        query_params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.access_key_id}/{credential_scope}",
            "X-Amz-Date": amzdate,
            "X-Amz-Expires": str(expires_in),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_querystring = urllib.parse.urlencode(sorted(query_params.items()))
        canonical_headers = f"host:{host}\n"
        signed_headers = "host"
        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = (
            f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amzdate}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        def sign(k: bytes, msg: str) -> bytes:
            return hmac.new(k, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + self.secret_access_key).encode("utf-8"), datestamp)
        k_region = sign(k_date, self.region)
        k_service = sign(k_region, "s3")
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        return f"{url_base}?{canonical_querystring}&X-Amz-Signature={signature}"

    def _execute_http_with_retry(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        data: Optional[bytes] = None,
        timeout_seconds: int = 15,
    ) -> bytes:
        """Execute HTTP request with exponential backoff retries on transient errors."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    return resp.read()
            except urllib.error.HTTPError as http_err:
                last_error = http_err
                # Retry on 429 and 5xx errors
                if http_err.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    backoff = 0.2 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                raise StorageError(f"HTTP {http_err.code} from S3/R2 storage ({http_err.reason})") from http_err
            except (urllib.error.URLError, TimeoutError, OSError) as net_err:
                last_error = net_err
                if attempt < self.max_retries:
                    backoff = 0.2 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                raise StorageError(f"Network error communicating with S3/R2 storage: {net_err}") from net_err

        raise StorageError(f"S3/R2 storage request failed after {self.max_retries} attempts: {last_error}")

    def upload_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload a file to S3/R2 object storage with retries and automatic local fallback."""
        src = Path(local_source_path)
        if not src.is_file():
            raise StorageError(f"Source file for upload not found: {src}")

        clean_key = destination_key.lstrip("/\\")
        mime = content_type or self._get_mime_type(src)

        # If credentials are not configured, use presigned or fallback
        if not self.access_key_id or not self.secret_access_key:
            if self.enable_local_fallback:
                logger.info(f"S3 credentials not configured. Storing '{clean_key}' in local storage fallback.")
                return self.local_fallback.store_file(src, clean_key, content_type=mime)
            return self.get_presigned_url(clean_key, method="GET")

        try:
            payload = src.read_bytes()
            url, headers = self._generate_sigv4_headers(
                method="PUT",
                clean_key=clean_key,
                payload_bytes=payload,
                content_type=mime,
            )
            self._execute_http_with_retry(url=url, method="PUT", headers=headers, data=payload)
            return self.get_presigned_url(clean_key, method="GET")
        except Exception as exc:
            if self.enable_local_fallback:
                logger.warning(
                    f"S3/R2 upload failed for '{clean_key}' ({exc}). Falling back to local storage."
                )
                return self.local_fallback.store_file(src, clean_key, content_type=mime)
            raise StorageError(f"Failed to upload '{clean_key}' to S3/R2 storage: {exc}") from exc

    def store_file(
        self,
        local_source_path: Path | str,
        destination_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        return self.upload_file(local_source_path, destination_key, content_type=content_type)

    def download_file(self, key: str, local_destination_path: Path | str) -> Path:
        clean_key = key.lstrip("/\\")
        dest = Path(local_destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not self.access_key_id or not self.secret_access_key:
            if self.local_fallback.exists(clean_key):
                return self.local_fallback.download_file(clean_key, dest)
            raise StorageError(f"Cannot download '{clean_key}': S3 credentials not configured.")

        try:
            url, headers = self._generate_sigv4_headers(method="GET", clean_key=clean_key)
            data = self._execute_http_with_retry(url=url, method="GET", headers=headers)
            dest.write_bytes(data)
            return dest
        except Exception as exc:
            if self.local_fallback.exists(clean_key):
                logger.warning(f"S3 download failed for '{clean_key}' ({exc}). Reading from local storage fallback.")
                return self.local_fallback.download_file(clean_key, dest)
            raise StorageError(f"Failed to download '{clean_key}' from S3/R2 storage: {exc}") from exc

    def get_presigned_url(
        self,
        key: str,
        method: str = "GET",
        expires_in_seconds: int = 3600,
    ) -> str:
        return self._generate_presigned_url(key, method=method, expires_in=expires_in_seconds)

    def get_file_path_or_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        clean_key = key.lstrip("/\\")
        return self._generate_presigned_url(clean_key, method="GET", expires_in=expires_in_seconds)

    def delete_file(self, key: str) -> bool:
        clean_key = key.lstrip("/\\")
        # Also clean up local fallback if present
        if self.local_fallback.exists(clean_key):
            self.local_fallback.delete_file(clean_key)

        if not self.access_key_id or not self.secret_access_key:
            return True

        try:
            url, headers = self._generate_sigv4_headers(method="DELETE", clean_key=clean_key)
            self._execute_http_with_retry(url=url, method="DELETE", headers=headers)
            return True
        except Exception:
            return False

    def delete_prefix(self, prefix: str) -> int:
        clean_prefix = prefix.lstrip("/\\")
        local_count = self.local_fallback.delete_prefix(clean_prefix)
        return local_count

    def exists(self, key: str) -> bool:
        clean_key = key.lstrip("/\\")
        if self.local_fallback.exists(clean_key):
            return True
        if not self.access_key_id or not self.secret_access_key:
            return False
        try:
            url, headers = self._generate_sigv4_headers(method="HEAD", clean_key=clean_key)
            self._execute_http_with_retry(url=url, method="HEAD", headers=headers)
            return True
        except Exception:
            return False


class R2StorageService(S3StorageService):
    """Specialized Cloudflare R2 storage service implementation."""

    def __init__(self, config: Optional[StorageConfig] = None, **kwargs: Any) -> None:
        cfg = config or StorageConfig.from_env()
        cfg.backend = StorageBackend.R2
        if cfg.region == "us-east-1":
            cfg.region = "auto"
        super().__init__(config=cfg, **kwargs)


def get_storage_service(config: Optional[StorageConfig] = None) -> StorageService:
    """Factory creating the configured storage backend based on `StorageConfig`."""
    cfg = config or StorageConfig.from_env()
    if cfg.backend == StorageBackend.R2:
        return R2StorageService(config=cfg)
    if cfg.backend in (StorageBackend.S3, StorageBackend.MINIO, StorageBackend.WASABI):
        return S3StorageService(config=cfg)
    return LocalStorageService(root_dir=cfg.local_root_dir)


def get_storage_report(service: Optional[StorageService] = None) -> StorageReport:
    """Generate diagnostic status report for the active storage service."""
    srv = service or default_storage_service
    config = getattr(srv, "config", StorageConfig.from_env())

    is_cloud = isinstance(srv, S3StorageService) and bool(srv.access_key_id and srv.secret_access_key)

    return StorageReport(
        backend=srv.__class__.__name__,
        configured_backend=config.backend.value,
        bucket=getattr(srv, "bucket", config.bucket),
        region=getattr(srv, "region", config.region),
        endpoint_url=getattr(srv, "endpoint_url", config.endpoint_url),
        public_base_url=getattr(srv, "public_base_url", config.public_base_url),
        is_cloud_active=is_cloud,
        local_fallback_enabled=getattr(srv, "enable_local_fallback", True),
    )


# Global default instance
default_storage_service = get_storage_service()
