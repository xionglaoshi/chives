'use strict';

// The child owns the schedule. The core answers after sharing its existing
// caches, settings and notification store with the requested operation.
const interval = Number(process.argv[3]);
const delay = Number(process.argv[4]);
if (!process.send || !Number.isSafeInteger(interval) || interval < 1 ||
    !Number.isSafeInteger(delay) || delay < 0) process.exit(64);

function wake() {
  process.send('tick');
}

process.on('message', message => {
  if (message === 'complete') setTimeout(wake, interval);
});
process.on('disconnect', () => process.exit(0));
process.send('ready');
setTimeout(wake, delay);
