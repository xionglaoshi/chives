import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const CHIVES_SERVER_PORT = 8880;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8888,
    strictPort: true,
    fs: {
      deny: ['.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml', '**/.git/**', '**/midas-contrib/**', '**/data/**', '**/user-data/**', '**/public-data/**', '**/workspace/**', '**/runtime/**', '**/.credentials.yaml', '**/.credentials.yaml.*'],
    },
    proxy: {
      '/api': `http://127.0.0.1:${CHIVES_SERVER_PORT}`
    }
  }
});
