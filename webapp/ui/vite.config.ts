import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {

  const env = loadEnv(mode, process.cwd(), '');

  return {
    server: {
      port: env.VITE_PORT || 2000,
      strictPort: true,
      host: true
    },
    plugins: [react()],
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/setupTests.ts'],
      include: ['**/*.test.{ts,tsx}']
    }
  };
});