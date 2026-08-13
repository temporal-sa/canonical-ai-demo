// Worker entrypoint: polls the task queue, runs the workflow + activities (LLM,
// tools, DB, research). Same crash-recovery beat as python/worker.py — kill it
// mid-conversation and restart; the loop resumes from history.
//
//     npm run worker    (or: make worker-ts)

import { Worker } from '@temporalio/worker';
import * as activities from './activities';
import * as control from './activities/control';
import * as config from './config';

async function main(): Promise<void> {
  const connection = await config.workerConnection();
  // A client so LLM activities can read their conversation's kill-switch.
  control.setClient(await config.makeClient());

  const worker = await Worker.create({
    connection,
    namespace: config.TEMPORAL_NAMESPACE,
    taskQueue: config.TASK_QUEUE,
    workflowsPath: require.resolve('./agent'),
    activities,
  });

  console.log(
    `ts worker polling task queue '${config.TASK_QUEUE}' on ${config.TEMPORAL_ADDRESS} ` +
      `(namespace: ${config.TEMPORAL_NAMESPACE}, provider: ${config.LLM_PROVIDER})`
  );
  await worker.run();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
