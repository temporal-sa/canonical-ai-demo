package io.temporal.demo.travel;

import io.temporal.activity.Activity;
import io.temporal.client.WorkflowClient;
import io.temporal.client.WorkflowStub;
import io.temporal.demo.travel.Models.CheckoutRequest;
import io.temporal.demo.travel.Models.CheckoutReservation;
import io.temporal.demo.travel.Models.CheckoutStepRequest;
import io.temporal.demo.travel.Models.FinalizeCheckoutResult;
import io.temporal.demo.travel.Models.ItineraryItem;
import io.temporal.demo.travel.Models.LlmRequest;
import io.temporal.demo.travel.Models.LlmResponse;
import io.temporal.demo.travel.Models.ReportData;
import io.temporal.demo.travel.Models.SearchItem;
import io.temporal.demo.travel.Models.SearchPlan;
import io.temporal.demo.travel.Models.ToolRequest;
import io.temporal.demo.travel.Models.WriteRequest;
import io.temporal.failure.ApplicationFailure;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

final class AgentActivitiesImpl implements AgentActivities {
  private final Config config;
  private final Database database;
  private final WorkflowClient temporal;
  private final AnthropicClient anthropic;

  AgentActivitiesImpl(Config config, Database database, WorkflowClient temporal) {
    this.config = config;
    this.database = database;
    this.temporal = temporal;
    this.anthropic = new AnthropicClient(config);
  }

  @Override
  public LlmResponse callLlm(LlmRequest request) {
    guardLlm();
    return anthropic.callLlm(request);
  }

  @Override
  public SearchPlan planSearches(String brief) {
    guardLlm();
    return anthropic.planSearches(brief, config.researchSearches());
  }

  @Override
  public String webSearch(SearchItem item) {
    guardLlm();
    if (Activity.getExecutionContext().getInfo().getAttempt() == 1
        && ThreadLocalRandom.current().nextDouble() < config.webSearchFailRate()) {
      throw ApplicationFailure.newFailure("web_search transient failure (simulated) for " + item.query(), "WebSearchFlaky");
    }
    return anthropic.webSearch(item, config.webSearchMaxUses());
  }

  @Override
  public ReportData writeReport(WriteRequest request) {
    guardLlm();
    return anthropic.writeReport(request.brief(), request.findings());
  }

  @Override
  public String executeTool(ToolRequest request) {
    pause(config.toolDelay());
    Map<String, Object> args = request.call().args();
    try {
      Object result = switch (request.call().name()) {
        case "search_events" -> database.searchEvents(text(args, "destination"), args.get("month"));
        case "search_destinations" -> database.searchDestinations(text(args, "query"));
        case "get_destination_info" -> database.getDestinationInfo(text(args, "destination"));
        case "search_flights" -> database.searchFlights(text(args, "destination"), text(args, "origin"), text(args, "depart_date"));
        case "search_hotels" -> database.searchHotels(text(args, "destination"), args.get("max_price") == null ? null : Database.decimal(args.get("max_price")));
        case "search_attractions" -> database.searchAttractions(text(args, "destination"));
        case "get_bookings" -> database.getBookings(request.account_key());
        case "get_booking_details" -> database.getBookingDetails(Database.whole(args.get("booking_id")));
        case "add_to_itinerary" -> database.getItineraryItems(mapList(args.get("items")));
        case "create_invoice" -> database.recordInvoice(request.account_key(), Database.decimal(args.get("amount")), text(args, "flight_details"));
        default -> throw ApplicationFailure.newNonRetryableFailure("Unknown tool: " + request.call().name(), "UnknownTool");
      };
      return AnthropicClient.json(result);
    } catch (Database.BusinessException error) {
      return AnthropicClient.json(Map.of("error", error.getMessage()));
    }
  }

  @Override public CheckoutReservation bookFlight(CheckoutStepRequest request) { pause(config.checkoutStepDelay()); return reservation(request); }

  @Override
  public CheckoutReservation bookHotel(CheckoutStepRequest request) {
    pause(config.checkoutStepDelay());
    if (shouldSimulateHotelFailure(config.checkoutFailHotel(), request.simulate_hotel_failure())) {
      throw ApplicationFailure.newNonRetryableFailure(
          "Hotel booking failed — the supplier returned no availability (injected demo failure).", "HotelBookingFailed");
    }
    return reservation(request);
  }

  static boolean shouldSimulateHotelFailure(boolean enabled, boolean requestedForAttempt) {
    return enabled && requestedForAttempt;
  }

  @Override public CheckoutReservation bookActivity(CheckoutStepRequest request) { pause(config.checkoutStepDelay()); return reservation(request); }
  @Override public CheckoutReservation cancelFlight(CheckoutReservation reservation) { return cancel(reservation); }
  @Override public CheckoutReservation cancelHotel(CheckoutReservation reservation) { return cancel(reservation); }
  @Override public CheckoutReservation cancelActivity(CheckoutReservation reservation) { return cancel(reservation); }

  @Override
  public FinalizeCheckoutResult finalizeCheckout(CheckoutRequest request) {
    List<Map<String, Object>> already = database.itemsAlreadyBooked(request.account_key(), request.items());
    if (!already.isEmpty()) {
      String names = already.stream().map(item -> "\"" + item.get("title") + "\"").reduce((a, b) -> a + ", " + b).orElse("");
      throw ApplicationFailure.newNonRetryableFailure("Booking declined — this trip already includes " + names + ".", "BookingDeclined");
    }
    Map<String, Object> booking = database.recordBooking(request.account_key(), request.items(), request.summary());
    return new FinalizeCheckoutResult(Database.whole(booking.get("booking_id")));
  }

  private void guardLlm() {
    try {
      String workflowId = Activity.getExecutionContext().getInfo().getWorkflowId();
      WorkflowStub stub = temporal.newUntypedWorkflowStub(workflowId);
      Boolean down = stub.query("is_llm_down", Boolean.class);
      if (Boolean.TRUE.equals(down)) throw ApplicationFailure.newFailure("LLM provider is unavailable (simulated outage).", "LLMProviderDown");
    } catch (ApplicationFailure failure) {
      throw failure;
    } catch (Exception ignored) {
      // The demo switch can never break the real provider call.
    }
  }

  private CheckoutReservation reservation(CheckoutStepRequest request) {
    String raw = "%s:%s:%d".formatted(request.account_key(), request.item().kind(), request.item().ref_id());
    String prefix = switch (request.item().kind()) { case "flight" -> "FLT"; case "hotel" -> "HTL"; default -> "ACT"; };
    try {
      String suffix = HexFormat.of().withUpperCase().formatHex(MessageDigest.getInstance("SHA-256").digest(raw.getBytes(StandardCharsets.UTF_8))).substring(0, 10);
      return new CheckoutReservation(request.item().kind(), request.item().ref_id(), request.item().title(), prefix + "-" + suffix, "booked");
    } catch (NoSuchAlgorithmException impossible) {
      throw new IllegalStateException(impossible);
    }
  }

  private CheckoutReservation cancel(CheckoutReservation reservation) {
    pause(config.checkoutStepDelay());
    return new CheckoutReservation(reservation.kind(), reservation.ref_id(), reservation.title(), reservation.reservation_id(), "cancelled");
  }

  private static void pause(java.time.Duration duration) {
    if (duration.isZero()) return;
    try { Thread.sleep(duration.toMillis()); }
    catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new RuntimeException(error); }
  }

  private static String text(Map<String, Object> args, String key) { return Database.text(args.get(key)); }

  @SuppressWarnings("unchecked")
  private static List<Map<String, Object>> mapList(Object value) {
    if (!(value instanceof List<?> list)) return List.of();
    List<Map<String, Object>> result = new ArrayList<>();
    for (Object item : list) if (item instanceof Map<?, ?> map) result.add((Map<String, Object>) map);
    return result;
  }
}
