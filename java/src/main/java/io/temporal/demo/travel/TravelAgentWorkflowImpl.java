package io.temporal.demo.travel;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import io.temporal.activity.ActivityOptions;
import io.temporal.api.enums.v1.ParentClosePolicy;
import io.temporal.common.RetryOptions;
import io.temporal.demo.travel.Models.ApprovalDecision;
import io.temporal.demo.travel.Models.ChatMessage;
import io.temporal.demo.travel.Models.CheckoutRequest;
import io.temporal.demo.travel.Models.CheckoutResult;
import io.temporal.demo.travel.Models.ItineraryItem;
import io.temporal.demo.travel.Models.LlmRequest;
import io.temporal.demo.travel.Models.LlmResponse;
import io.temporal.demo.travel.Models.PendingConfirmation;
import io.temporal.demo.travel.Models.ReportData;
import io.temporal.demo.travel.Models.ResearchStatus;
import io.temporal.demo.travel.Models.SearchItem;
import io.temporal.demo.travel.Models.SearchPlan;
import io.temporal.demo.travel.Models.ToolCall;
import io.temporal.demo.travel.Models.ToolRequest;
import io.temporal.demo.travel.Models.TurnResult;
import io.temporal.demo.travel.Models.WriteRequest;
import io.temporal.failure.ActivityFailure;
import io.temporal.failure.ApplicationFailure;
import io.temporal.failure.ChildWorkflowFailure;
import io.temporal.workflow.Async;
import io.temporal.workflow.ChildWorkflowOptions;
import io.temporal.workflow.Promise;
import io.temporal.workflow.Workflow;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public class TravelAgentWorkflowImpl implements TravelAgentWorkflow {
  private static final RetryOptions LLM_RETRY = RetryOptions.newBuilder()
      .setInitialInterval(Duration.ofSeconds(1)).setBackoffCoefficient(2)
      .setMaximumInterval(Duration.ofSeconds(10)).setDoNotRetry("LLMFatalError").build();
  private static final RetryOptions TOOL_RETRY = RetryOptions.newBuilder()
      .setInitialInterval(Duration.ofSeconds(1)).setBackoffCoefficient(2)
      .setMaximumInterval(Duration.ofSeconds(10)).setDoNotRetry("BookingDeclined").build();

  private final AgentActivities llm = activities(60, LLM_RETRY);
  private final AgentActivities planner = activities(90, LLM_RETRY);
  private final AgentActivities searcher = activities(120, LLM_RETRY);
  private final AgentActivities writer = activities(180, LLM_RETRY);
  private final AgentActivities tools = activities(30, TOOL_RETRY);

  private final List<ChatMessage> messages = new ArrayList<>();
  private String accountKey;
  private PendingConfirmation pendingConfirmation;
  private ApprovalDecision approval;
  private boolean turnInProgress;
  private boolean llmDown;
  private int checkoutAttempt;
  private List<ItineraryItem> itinerary = new ArrayList<>();
  private String phase = "idle";
  private List<SearchItem> plan = new ArrayList<>();
  private int searchesTotal;
  private int searchesDone;

  @Override
  public void run(String travellerEmail) {
    accountKey = Workflow.getInfo().getWorkflowId();
    messages.add(ChatMessage.text("system", Prompts.systemPrompt(travellerEmail)));
    while (true) {
      Workflow.await(() -> turnInProgress);
      while (true) {
        LlmResponse response = think();
        messages.add(response.message());
        List<ToolCall> calls = response.message().tool_calls() == null ? List.of() : response.message().tool_calls();
        if (calls.isEmpty()) break;
        String finalAnswer = null;
        for (ToolCall call : calls) {
          ToolOutcome outcome = dispatch(call);
          messages.add(ChatMessage.tool(outcome.result(), call.id()));
          if (outcome.terminal()) finalAnswer = outcome.assistantText();
        }
        if (finalAnswer != null) {
          messages.add(ChatMessage.text("assistant", finalAnswer));
          break;
        }
      }
      phase = "idle";
      turnInProgress = false;
    }
  }

  private LlmResponse think() {
    try {
      return llm.callLlm(new LlmRequest(List.copyOf(messages)));
    } catch (ActivityFailure error) {
      return new LlmResponse(ChatMessage.text("assistant", "I'm sorry — I hit an error I couldn't recover from. Please try again in a moment."));
    }
  }

  private ToolOutcome dispatch(ToolCall call) {
    try {
      return switch (call.name()) {
        case "research_destination" -> research(Database.text(call.args().get("query")));
        case "add_to_itinerary" -> addToItinerary(call);
        case "remove_from_itinerary" -> removeFromItinerary(call);
        case "book_trip" -> bookTrip();
        case "create_invoice" -> createInvoice(call);
        default -> new ToolOutcome(runTool(call), false, "");
      };
    } catch (ActivityFailure | ChildWorkflowFailure error) {
      return new ToolOutcome(AnthropicClient.json(ordered("error", failureMessage(error))), false, "");
    }
  }

  private String runTool(ToolCall call) {
    return tools.executeTool(new ToolRequest(call, accountKey));
  }

  private ToolOutcome research(String query) {
    plan = new ArrayList<>();
    searchesTotal = searchesDone = 0;
    phase = "planning";
    SearchPlan searchPlan = planner.planSearches(query);
    plan = new ArrayList<>(searchPlan.searches());
    searchesTotal = plan.size();
    phase = "searching";
    List<Promise<String>> promises = plan.stream().map(item -> Async.function(searcher::webSearch, item)).toList();
    List<String> findings = new ArrayList<>();
    for (Promise<String> promise : promises) {
      findings.add(promise.get());
      searchesDone++;
    }
    phase = "writing";
    ReportData report = writer.writeReport(new WriteRequest(query, findings));
    phase = "idle";
    return new ToolOutcome(report.short_summary() + "\n\n" + report.markdown_report(), true, report.markdown_report());
  }

  private ToolOutcome addToItinerary(ToolCall call) {
    String result = runTool(call);
    List<ItineraryItem> resolved;
    try {
      resolved = AnthropicClient.JSON.readValue(result, new TypeReference<>() {});
    } catch (JsonProcessingException error) {
      return new ToolOutcome(result, false, "");
    }
    Set<String> existing = new HashSet<>();
    itinerary.forEach(item -> existing.add(itemId(item)));
    List<Map<String, Object>> added = new ArrayList<>();
    for (ItineraryItem item : resolved) {
      if (!existing.add(itemId(item))) continue;
      itinerary.add(item);
      added.add(ordered("item_id", itemId(item), "title", item.title()));
    }
    return new ToolOutcome(AnthropicClient.json(ordered(
        "added", added, "itinerary_size", itinerary.size(), "itinerary_total", itineraryTotal())), false, "");
  }

  private ToolOutcome removeFromItinerary(ToolCall call) {
    Set<String> ids = new HashSet<>();
    for (Object id : AnthropicClient.list(call.args().get("item_ids"))) ids.add(Database.text(id));
    int before = itinerary.size();
    itinerary = new ArrayList<>(itinerary.stream().filter(item -> !ids.contains(itemId(item))).toList());
    return new ToolOutcome(AnthropicClient.json(ordered(
        "removed", before - itinerary.size(), "itinerary_size", itinerary.size(), "itinerary_total", itineraryTotal())), false, "");
  }

  private ToolOutcome bookTrip() {
    if (itinerary.isEmpty()) return new ToolOutcome(AnthropicClient.json(ordered("error", "The itinerary is empty — add flights, hotels, or activities before booking.")), false, "");
    double total = itineraryTotal();
    String summary = String.format(Locale.ROOT, "%d item(s) — $%.2f", itinerary.size(), total);
    List<Map<String, Object>> items = itinerary.stream().map(item -> ordered("title", item.title(), "price", item.price())).toList();
    pendingConfirmation = new PendingConfirmation("book_trip", "Booking approval required", summary, total, ordered("items", items));
    ApprovalDecision decision = awaitApproval();
    if (!decision.approved()) return new ToolOutcome("The traveller DECLINED this booking." + reason(decision), false, "");
    CheckoutWorkflow child = Workflow.newChildWorkflowStub(CheckoutWorkflow.class, ChildWorkflowOptions.newBuilder()
        .setWorkflowId("%s-checkout-%d".formatted(accountKey, ++checkoutAttempt))
        .setParentClosePolicy(ParentClosePolicy.PARENT_CLOSE_POLICY_REQUEST_CANCEL).build());
    CheckoutResult checkout = child.run(new CheckoutRequest(accountKey, List.copyOf(itinerary), summary));
    if ("booked".equals(checkout.status())) itinerary = new ArrayList<>();
    return new ToolOutcome(AnthropicClient.json(checkout), false, "");
  }

  private ToolOutcome createInvoice(ToolCall call) {
    double amount = Database.round2(Database.decimal(call.args().getOrDefault("amount", 0)));
    String details = Database.text(call.args().get("flight_details"));
    if (amount <= 0 || details.isBlank()) return new ToolOutcome(AnthropicClient.json(ordered("error", "Need a positive amount and a flight description to create an invoice.")), false, "");
    pendingConfirmation = new PendingConfirmation("create_invoice", "Create invoice", details, amount, ordered("amount", amount, "flight_details", details));
    ApprovalDecision decision = awaitApproval();
    if (!decision.approved()) return new ToolOutcome("The traveller DECLINED the invoice." + reason(decision), false, "");
    return new ToolOutcome(runTool(new ToolCall("invoice", "create_invoice", ordered("amount", amount, "flight_details", details))), false, "");
  }

  private ApprovalDecision awaitApproval() {
    Workflow.await(() -> approval != null);
    ApprovalDecision decision = approval;
    approval = null;
    pendingConfirmation = null;
    return decision;
  }

  @Override
  public TurnResult sendMessage(String text) {
    if (turnInProgress) throw ApplicationFailure.newNonRetryableFailure("A turn is already in progress.", "TurnInProgress");
    int start = messages.size();
    messages.add(ChatMessage.text("user", text));
    turnInProgress = true;
    Workflow.await(() -> !turnInProgress || pendingConfirmation != null);
    String reply = lastAssistant(start);
    return pendingConfirmation == null ? new TurnResult("reply", reply) : new TurnResult("awaiting_approval", reply);
  }

  @Override public void confirmAction(ApprovalDecision decision) { approval = decision; }
  @Override public void setLlmStatus(boolean down) { llmDown = down; }
  @Override public boolean isLlmDown() { return llmDown; }
  @Override public PendingConfirmation pendingApproval() { return pendingConfirmation; }
  @Override public ResearchStatus researchStatus() { return new ResearchStatus(phase, List.copyOf(plan), searchesTotal, searchesDone); }
  @Override public List<ItineraryItem> itineraryView() { return List.copyOf(itinerary); }

  @Override
  public List<ChatMessage> transcript() {
    return messages.stream().filter(message -> ("user".equals(message.role()) || "assistant".equals(message.role()))
        && message.content() != null && !message.content().isBlank()).toList();
  }

  private String lastAssistant(int start) {
    for (int i = messages.size() - 1; i >= start; i--) {
      ChatMessage message = messages.get(i);
      if ("assistant".equals(message.role()) && message.content() != null && !message.content().isBlank()) return message.content();
    }
    return "";
  }

  private static AgentActivities activities(int seconds, RetryOptions retry) {
    return Workflow.newActivityStub(AgentActivities.class, ActivityOptions.newBuilder()
        .setStartToCloseTimeout(Duration.ofSeconds(seconds)).setRetryOptions(retry).build());
  }

  private String itemId(ItineraryItem item) { return item.kind() + "-" + item.ref_id(); }
  private double itineraryTotal() { return Database.round2(itinerary.stream().mapToDouble(ItineraryItem::price).sum()); }
  private static String reason(ApprovalDecision decision) { return decision.reason() == null || decision.reason().isBlank() ? "" : " Reason: " + decision.reason(); }
  private static Map<String, Object> ordered(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }
  private static String failureMessage(RuntimeException error) {
    Throwable current = error;
    while (current.getCause() != null) current = current.getCause();
    return current.getMessage() == null ? "That action could not be completed." : current.getMessage();
  }

  private record ToolOutcome(String result, boolean terminal, String assistantText) {}
}
