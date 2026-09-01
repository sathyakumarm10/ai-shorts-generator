import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import {
  getCurrentUser,
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  refreshTokens as apiRefreshTokens,
} from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    try {
      const u = await getCurrentUser()
      setUser(u)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = async (email, password) => {
    const res = await apiLogin(email, password)
    setUser(res.user)
    return res
  }

  const register = async (email, password) => {
    const res = await apiRegister(email, password)
    setUser(res.user)
    return res
  }

  const logout = async () => {
    await apiLogout()
    setUser(null)
  }

  const refreshUser = async () => {
    const refreshed = await apiRefreshTokens()
    if (refreshed && refreshed.user) {
      setUser(refreshed.user)
      return refreshed.user
    }
    setUser(null)
    return null
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser, reloadUser: loadUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    return {
      user: null,
      loading: false,
      login: async () => ({}),
      register: async () => ({}),
      logout: async () => {},
      refreshUser: async () => null,
      reloadUser: async () => {},
    }
  }
  return ctx
}
