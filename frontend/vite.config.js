import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^antd$/, replacement: fileURLToPath(new URL('./src/antd-x-bridge.js', import.meta.url)) },
      { find: /^@ant-design\/icons$/, replacement: fileURLToPath(new URL('./src/icons-bridge.js', import.meta.url)) },
    ],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const modulePath = id.replace(/\\/g, '/')
          const component = modulePath.match(/\/node_modules\/antd\/es\/([^/]+)\/index\.js$/)?.[1]
          if (!component) return undefined
          if (['form', 'input', 'select', 'upload'].includes(component)) return 'antd-input'
          if (['modal', 'drawer', 'dropdown', 'popconfirm', 'tooltip'].includes(component)) return 'antd-overlay'
          if (['layout', 'menu', 'steps', 'tabs'].includes(component)) return 'antd-navigation'
          if (component === 'card') return 'antd-card'
          if (component === 'list') return 'antd-list'
          if (component === 'empty') return 'antd-empty'
          if (['avatar', 'badge', 'descriptions', 'progress', 'statistic', 'tag'].includes(component)) return 'antd-status'
          if (['app', 'button', 'config-provider', 'flex', 'grid', 'space', 'spin', 'typography', 'theme'].includes(component)) return 'antd-foundation'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
