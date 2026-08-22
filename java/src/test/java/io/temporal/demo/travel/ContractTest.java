package io.temporal.demo.travel;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import io.temporal.demo.travel.Models.ResearchStatus;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

class ContractTest {
  @Test
  void gatewayDtosUseSnakeCase() {
    JsonNode json = AnthropicClient.JSON.valueToTree(new ResearchStatus("searching", List.of(), 3, 2));
    assertTrue(json.has("searches_total"));
    assertTrue(json.has("searches_done"));
  }

  @Test
  void toolCatalogMatchesContract() {
    Set<String> actual = Prompts.TOOLS.stream().map(tool -> (String) tool.get("name")).collect(Collectors.toSet());
    assertEquals(Set.of(
        "search_events", "search_destinations", "get_destination_info", "search_flights",
        "search_hotels", "search_attractions", "research_destination", "create_invoice",
        "add_to_itinerary", "remove_from_itinerary", "book_trip", "get_bookings",
        "get_booking_details"), actual);
  }
}
