package io.temporal.demo.travel;

import io.temporal.client.WorkflowClient;
import io.temporal.client.WorkflowClientOptions;
import io.temporal.serviceclient.WorkflowServiceStubs;
import io.temporal.serviceclient.WorkflowServiceStubsOptions;
import io.temporal.worker.Worker;
import io.temporal.worker.WorkerFactory;

public final class WorkerMain {
  private WorkerMain() {}

  public static void main(String[] args) {
    Config config = Config.load();
    WorkflowServiceStubsOptions.Builder serviceOptions = WorkflowServiceStubsOptions.newBuilder()
        .setTarget(config.temporalAddress());
    if (!config.temporalApiKey().isBlank()) {
      serviceOptions
          .setEnableHttps(true)
          .addApiKey(() -> config.temporalApiKey());
    }
    if (!config.temporalTlsCert().isBlank() || !config.temporalTlsKey().isBlank()) {
      throw new IllegalArgumentException("The Java local worker currently supports Temporal Cloud API-key auth; mTLS is not configured in this runbook.");
    }
    WorkflowServiceStubs service = WorkflowServiceStubs.newServiceStubs(serviceOptions.build());
    WorkflowClient temporal = WorkflowClient.newInstance(service,
        WorkflowClientOptions.newBuilder().setNamespace(config.temporalNamespace()).build());
    WorkerFactory factory = WorkerFactory.newInstance(temporal);
    Worker worker = factory.newWorker(config.taskQueue());
    worker.registerWorkflowImplementationTypes(TravelAgentWorkflowImpl.class, CheckoutWorkflowImpl.class);
    worker.registerActivitiesImplementations(new AgentActivitiesImpl(config, new Database(config.dbUrl()), temporal));
    factory.start();
    System.out.printf("java worker polling task queue '%s' on %s (namespace: %s, provider: %s)%n",
        config.taskQueue(), config.temporalAddress(), config.temporalNamespace(), config.llmProvider());
  }
}
