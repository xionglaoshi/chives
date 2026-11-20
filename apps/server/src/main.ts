import { createApp } from './app.js';
import { loadConfig } from './config.js';
import { CHIVES_SERVER_HOST } from './index.js';

const config = loadConfig();
const app = createApp({ config });

app.server.listen(config.port, CHIVES_SERVER_HOST, () => {
  console.log(`Chives server listening on http://${CHIVES_SERVER_HOST}:${config.port}`);
  console.log(`harness=${config.harness} data=${config.dataDir}`);
});

let shuttingDown = false;
const shutdown = (signal: string): void => {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`Chives server shutting down (${signal})`);
  const force = setTimeout(() => process.exit(1), 5000);
  force.unref();
  app.sse.closeAll();
  app.server.close(() => {
    void app
      .close()
      .catch((error: unknown) => {
        console.error('shutdown failed', error);
      })
      .finally(() => {
        clearTimeout(force);
        process.exit(0);
      });
  });
};

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
