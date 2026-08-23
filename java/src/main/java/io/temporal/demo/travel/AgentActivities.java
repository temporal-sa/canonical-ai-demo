package io.temporal.demo.travel;

import io.temporal.activity.ActivityInterface;
import io.temporal.activity.ActivityMethod;
import io.temporal.demo.travel.Models.CheckoutRequest;
import io.temporal.demo.travel.Models.CheckoutReservation;
import io.temporal.demo.travel.Models.CheckoutStepRequest;
import io.temporal.demo.travel.Models.FinalizeCheckoutResult;
import io.temporal.demo.travel.Models.LlmRequest;
import io.temporal.demo.travel.Models.LlmResponse;
import io.temporal.demo.travel.Models.ReportData;
import io.temporal.demo.travel.Models.SearchItem;
import io.temporal.demo.travel.Models.SearchPlan;
import io.temporal.demo.travel.Models.ToolRequest;
import io.temporal.demo.travel.Models.WriteRequest;

@ActivityInterface
public interface AgentActivities {
  @ActivityMethod(name = "call_llm")
  LlmResponse callLlm(LlmRequest request);

  @ActivityMethod(name = "execute_tool")
  String executeTool(ToolRequest request);

  @ActivityMethod(name = "plan_searches")
  SearchPlan planSearches(String brief);

  @ActivityMethod(name = "web_search")
  String webSearch(SearchItem item);

  @ActivityMethod(name = "write_report")
  ReportData writeReport(WriteRequest request);

  @ActivityMethod(name = "book_flight")
  CheckoutReservation bookFlight(CheckoutStepRequest request);

  @ActivityMethod(name = "book_hotel")
  CheckoutReservation bookHotel(CheckoutStepRequest request);

  @ActivityMethod(name = "book_activity")
  CheckoutReservation bookActivity(CheckoutStepRequest request);

  @ActivityMethod(name = "cancel_flight")
  CheckoutReservation cancelFlight(CheckoutReservation reservation);

  @ActivityMethod(name = "cancel_hotel")
  CheckoutReservation cancelHotel(CheckoutReservation reservation);

  @ActivityMethod(name = "cancel_activity")
  CheckoutReservation cancelActivity(CheckoutReservation reservation);

  @ActivityMethod(name = "finalize_checkout")
  FinalizeCheckoutResult finalizeCheckout(CheckoutRequest request);
}
