Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$wavPath = [System.IO.Path]::Combine($PSScriptRoot, "..", "downloads", "uploads", "real_speech.wav")
$synth.SetOutputToWaveFile($wavPath)

$speechText = @"
Welcome to the ultimate artificial intelligence masterclass. Today we will explore how neural networks are transforming technology, productivity, and modern business. 
First, let us understand deep learning. Deep learning is capable of processing massive amounts of unstructured data such as speech, video, and text across thousands of domains.
Secondly, attention mechanisms and transformer models have unlocked natural language understanding at unprecedented scale, powering modern generative intelligence systems.
Next, we examine real-world applications. From autonomous vehicles to medical diagnostics and creative software, artificial intelligence is revolutionizing every major modern industry.
In addition, edge computing and on-device machine learning models enable real-time inference without needing cloud infrastructure or constant internet connectivity.
Finally, the key takeaway is that combining human creativity with machine intelligence delivers the best results. Thank you for listening, explore the possibilities, and make sure to subscribe.
"@

$synth.Speak($speechText)
$synth.Dispose()

$videoPath = [System.IO.Path]::Combine($PSScriptRoot, "..", "downloads", "uploads", "real_source_video.mp4")

# Mux audio with test video pattern using ffmpeg
ffmpeg -y -f lavfi -i testsrc=duration=75:size=1280x720:rate=30 -i $wavPath -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $videoPath

Write-Output "Successfully generated $videoPath"
