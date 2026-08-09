import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^antd$/, replacement: fileURLToPath(new URL('./src/antd-bridge.js', import.meta.url)) },
      { find: /^@ant-design\/icons$/, replacement: fileURLToPath(new URL('./src/icons-bridge.js', import.meta.url)) },
    ],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const modulePath = id.replace(/\\/g, '/')
          if (modulePath.endsWith('/node_modules/react/jsx-runtime.js') || modulePath.endsWith('/node_modules/react/index.js') || modulePath.endsWith('/node_modules/react-dom/client.js')) return 'react'
          const component = modulePath.match(/\/node_modules\/antd\/es\/([^/]+)\/index\.js$/)?.[1]
          if (!component) return undefined
          if (['form', 'input', 'select', 'switch'].includes(component)) return 'antd-input'
          if (['drawer', 'dropdown', 'modal', 'popconfirm'].includes(component)) return 'antd-overlay'
          if (['layout', 'menu'].includes(component)) return 'antd-navigation'
          if (component === 'table') return 'antd-table'
          if (component === 'card') return 'antd-card'
          if (['avatar', 'badge', 'descriptions', 'statistic', 'tag'].includes(component)) return 'antd-status'
          if (['app', 'button', 'config-provider', 'space', 'spin', 'typography', 'theme', 'row', 'col', 'grid'].includes(component)) return 'antd-foundation'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
