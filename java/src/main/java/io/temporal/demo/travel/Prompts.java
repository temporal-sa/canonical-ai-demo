package io.temporal.demo.travel;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class Prompts {
  private Prompts() {}

  static String systemPrompt(String email) {
    return """
        You are a friendly, knowledgeable travel planning assistant.

        The traveller you are helping is signed in as: %s

        Help travellers go from “where should I go?” to a booked trip. Use the tools for
        catalog facts, prices, schedules, and bookings—never guess them.

        Supported flows:
        1. Event travel: search_events, search_flights around the event, then
           create_invoice for the chosen flight.
        2. Full trip: destination/search tools, add_to_itinerary, then book_trip.

        get_destination_info is the quick default for one place. search_destinations finds
        catalog places by interests. research_destination is a slow live research fan-out;
        call it only when the traveller explicitly asks for deep research or a written guide.
        research results contain names, not catalog IDs, so use search tools before adding.

        A named destination means trip intent: proactively search a sensible flight, hotel,
        and one or two attractions, then add them. Pick sensible defaults unless a choice is
        consequential. add_to_itinerary takes {kind,id} items using search-result IDs.

        When asked to book or invoice, call book_trip/create_invoice directly. Their durable
        human approval gate supplies confirmation, so do not ask “are you sure?” first.
        Never claim success until the tool result says it succeeded. If checkout compensated,
        explain the failed step and what was cancelled. Keep replies short and conversational.
        If a tool returns an error, explain it plainly and suggest the next step.
        """.formatted(email);
  }

  static final List<Map<String, Object>> TOOLS = List.of(
      tool("search_events", "Find festivals, concerts, sports, and conferences at a destination, optionally in a month.",
          object(Map.of("destination", string("City or country"), "month", string("Optional month")), "destination")),
      tool("search_destinations", "Search the destination catalog by city, country, region, or interest.",
          object(Map.of("query", string("Search text or interest")), "query")),
      tool("get_destination_info", "Get quick facts and attractions for one destination.",
          object(Map.of("destination", string("City or country")), "destination")),
      tool("search_flights", "Search flights to a destination; optional origin and date. Any date works.",
          object(Map.of("destination", string("Destination city or code"), "origin", string("Optional origin"), "depart_date", string("Optional YYYY-MM-DD")), "destination")),
      tool("search_hotels", "Find hotels at a destination, optionally capped by nightly price.",
          object(Map.of("destination", string("Destination"), "max_price", number("Optional nightly cap")), "destination")),
      tool("search_attractions", "List activities at a destination with IDs, costs, and duration.",
          object(Map.of("destination", string("Destination")), "destination")),
      tool("research_destination", "Run a slow, live, multi-search deep-research pass only when explicitly requested.",
          object(Map.of("query", string("Focused self-contained research question")), "query")),
      tool("create_invoice", "Create an approval-gated invoice for one selected flight.",
          object(Map.of("amount", number("USD total"), "flight_details", string("Flight summary")), "amount", "flight_details")),
      tool("add_to_itinerary", "Stage catalog flights, hotels, and activities; nothing is booked yet.",
          object(Map.of("items", Map.of(
              "type", "array",
              "items", object(Map.of(
                  "kind", Map.of("type", "string", "enum", List.of("flight", "hotel", "activity")),
                  "id", Map.of("type", "integer")), "kind", "id"))), "items")),
      tool("remove_from_itinerary", "Remove staged items by kind-id item IDs.",
          object(Map.of("item_ids", Map.of("type", "array", "items", Map.of("type", "string"))), "item_ids")),
      tool("book_trip", "Approval-gated durable checkout of the current itinerary with compensation on failure.", object(Map.of())),
      tool("get_bookings", "List this conversation's booked trips.", object(Map.of())),
      tool("get_booking_details", "Get one booking's line items.",
          object(Map.of("booking_id", Map.of("type", "integer")), "booking_id")));

  static String planSystem(int count) {
    return "Produce exactly %d distinct, concise web searches for a travel research brief. Cover different facets such as highlights, neighborhoods, food, transport, season, day trips, budget, and safety. Return only the required structured data.".formatted(count);
  }

  static final String SEARCH_SYSTEM = "Use web search for the given travel query, then summarize the most useful factual findings in under 250 words. Include concrete names, costs, seasons, and travel times. Do not discuss your process.";

  static final String WRITE_SYSTEM = "Synthesize the supplied travel research findings into a cohesive 250–400 word Markdown destination guide grounded only in the findings. Return a two-to-three sentence short_summary and a markdown_report with compact headings and a useful table where appropriate.";

  static final Map<String, Object> PLAN_SCHEMA = schemaObject(Map.of(
      "searches", Map.of(
          "type", "array",
          "items", schemaObject(Map.of("query", Map.of("type", "string"), "reason", Map.of("type", "string")), "query", "reason"))), "searches");

  static final Map<String, Object> WRITE_SCHEMA = schemaObject(Map.of(
      "short_summary", Map.of("type", "string"),
      "markdown_report", Map.of("type", "string")), "short_summary", "markdown_report");

  private static Map<String, Object> tool(String name, String description, Map<String, Object> schema) {
    return linked("name", name, "description", description, "input_schema", schema);
  }

  private static Map<String, Object> string(String description) {
    return linked("type", "string", "description", description);
  }

  private static Map<String, Object> number(String description) {
    return linked("type", "number", "description", description);
  }

  private static Map<String, Object> object(Map<String, Object> properties, String... required) {
    Map<String, Object> result = linked("type", "object", "properties", properties);
    if (required.length > 0) result.put("required", List.of(required));
    return result;
  }

  private static Map<String, Object> schemaObject(Map<String, Object> properties, String... required) {
    Map<String, Object> result = object(properties, required);
    result.put("additionalProperties", false);
    return result;
  }

  private static Map<String, Object> linked(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }
}
