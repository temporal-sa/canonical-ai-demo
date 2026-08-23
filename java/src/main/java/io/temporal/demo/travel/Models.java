package io.temporal.demo.travel;

import java.util.List;
import java.util.Map;

public final class Models {
  private Models() {}

  public record ToolCall(String id, String name, Map<String, Object> args) {}

  public record ChatMessage(
      String role,
      String content,
      List<ToolCall> tool_calls,
      String tool_call_id) {
    public static ChatMessage text(String role, String content) {
      return new ChatMessage(role, content, List.of(), null);
    }

    public static ChatMessage tool(String content, String toolCallId) {
      return new ChatMessage("tool", content, List.of(), toolCallId);
    }
  }

  public record TurnResult(String status, String reply) {}
  public record ApprovalDecision(boolean approved, String reason) {}

  public record PendingConfirmation(
      String action,
      String title,
      String detail,
      double amount,
      Map<String, Object> args) {}

  public record SearchItem(String query, String reason) {}
  public record ResearchStatus(
      String phase,
      List<SearchItem> plan,
      int searches_total,
      int searches_done) {}

  public record ItineraryItem(
      String kind,
      long ref_id,
      String title,
      String subtitle,
      double price) {}

  public record CheckoutRequest(
      String account_key,
      List<ItineraryItem> items,
      String summary,
      boolean simulate_hotel_failure) {}

  public record CheckoutStepRequest(
      String account_key,
      ItineraryItem item,
      boolean simulate_hotel_failure) {}

  public record CheckoutReservation(
      String kind,
      long ref_id,
      String title,
      String reservation_id,
      String status) {}

  public record CheckoutResult(
      String status,
      String message,
      String workflow_id,
      List<CheckoutReservation> reservations,
      List<CheckoutReservation> compensations,
      String failure,
      Long booking_id) {}

  public record FinalizeCheckoutResult(long booking_id) {}
  public record LlmRequest(List<ChatMessage> messages) {}
  public record LlmResponse(ChatMessage message) {}
  public record ToolRequest(ToolCall call, String account_key) {}
  public record SearchPlan(List<SearchItem> searches) {}
  public record WriteRequest(String brief, List<String> findings) {}
  public record ReportData(String short_summary, String markdown_report) {}
}
