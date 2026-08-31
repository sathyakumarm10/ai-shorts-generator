import React, { createContext, useContext, useState, useEffect } from 'react'
import { getCurrentUser, login as apiLogin, register as apiRegister, logout as apiLogout } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadUser() {
      try {
        const u = await getCurrentUser()
        setUser(u)
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    }
    loadUser()
  }, [])

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

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
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
    }
  }
  return ctx
}
