package io.temporal.demo.travel;

import io.temporal.demo.travel.Models.ApprovalDecision;
import io.temporal.demo.travel.Models.ChatMessage;
import io.temporal.demo.travel.Models.ItineraryItem;
import io.temporal.demo.travel.Models.PendingConfirmation;
import io.temporal.demo.travel.Models.ResearchStatus;
import io.temporal.demo.travel.Models.TurnResult;
import io.temporal.workflow.QueryMethod;
import io.temporal.workflow.SignalMethod;
import io.temporal.workflow.UpdateMethod;
import io.temporal.workflow.WorkflowInterface;
import io.temporal.workflow.WorkflowMethod;
import java.util.List;

@WorkflowInterface
public interface TravelAgentWorkflow {
  @WorkflowMethod(name = "TravelAgentWorkflow")
  void run(String travellerEmail);

  @UpdateMethod(name = "send_message")
  TurnResult sendMessage(String text);

  @SignalMethod(name = "confirm_action")
  void confirmAction(ApprovalDecision decision);

  @SignalMethod(name = "set_llm_status")
  void setLlmStatus(boolean down);

  @QueryMethod(name = "is_llm_down")
  boolean isLlmDown();

  @QueryMethod(name = "transcript")
  List<ChatMessage> transcript();

  @QueryMethod(name = "pending_approval")
  PendingConfirmation pendingApproval();

  @QueryMethod(name = "research_status")
  ResearchStatus researchStatus();

  @QueryMethod(name = "itinerary_view")
  List<ItineraryItem> itineraryView();
}
