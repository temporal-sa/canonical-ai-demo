package io.temporal.demo.travel;

import io.temporal.client.WorkflowClient;
import io.temporal.client.WorkflowClientOptions;
import io.temporal.envconfig.ClientConfigProfile;
import io.temporal.envconfig.LoadClientConfigProfileOptions;
import io.temporal.serviceclient.WorkflowServiceStubs;
import io.temporal.serviceclient.WorkflowServiceStubsOptions;
import io.temporal.worker.Worker;
import io.temporal.worker.WorkerFactory;

import java.io.IOException;

public final class WorkerMain {
  private WorkerMain() {}

  public static void main(String[] args) {
    Config config = Config.load();
    try {
      ClientConfigProfile profile = ClientConfigProfile.load(LoadClientConfigProfileOptions.newBuilder()
                .setEnvOverrides(config.envValues())
                .build());
      WorkflowServiceStubsOptions serviceOptions = profile.toWorkflowServiceStubsOptions();
      WorkflowClientOptions clientOptions = profile.toWorkflowClientOptions();
      WorkflowClient temporalClient =
              WorkflowClient.newInstance(WorkflowServiceStubs.newServiceStubs(serviceOptions), clientOptions);
      WorkerFactory factory = WorkerFactory.newInstance(temporalClient);
      Worker worker = factory.newWorker(config.taskQueue());
      worker.registerWorkflowImplementationTypes(TravelAgentWorkflowImpl.class, CheckoutWorkflowImpl.class);
      worker.registerActivitiesImplementations(new AgentActivitiesImpl(config, new Database(config.dbUrl()), temporalClient));
      factory.start();
      System.out.printf("java worker polling task queue '%s' on %s (namespace: %s, provider: %s)%n",
          config.taskQueue(), config.temporalAddress(), config.temporalNamespace(), config.llmProvider());
    } catch (IOException e) {
      System.out.printf("Failed to load configuration %s%n", e.getMessage());
      System.exit(1);
    }
  }
}
