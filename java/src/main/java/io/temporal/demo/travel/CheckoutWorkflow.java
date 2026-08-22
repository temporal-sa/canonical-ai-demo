package io.temporal.demo.travel;

import io.temporal.demo.travel.Models.CheckoutRequest;
import io.temporal.demo.travel.Models.CheckoutResult;
import io.temporal.workflow.WorkflowInterface;
import io.temporal.workflow.WorkflowMethod;

@WorkflowInterface
public interface CheckoutWorkflow {
  @WorkflowMethod(name = "CheckoutWorkflow")
  CheckoutResult run(CheckoutRequest request);
}
