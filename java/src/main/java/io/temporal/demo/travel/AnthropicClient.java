package io.temporal.demo.travel;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.temporal.demo.travel.Models.ChatMessage;
import io.temporal.demo.travel.Models.LlmRequest;
import io.temporal.demo.travel.Models.LlmResponse;
import io.temporal.demo.travel.Models.ReportData;
import io.temporal.demo.travel.Models.SearchItem;
import io.temporal.demo.travel.Models.SearchPlan;
import io.temporal.demo.travel.Models.ToolCall;
import io.temporal.failure.ApplicationFailure;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class AnthropicClient {
  static final ObjectMapper JSON = new ObjectMapper();
  private final Config config;
  private final HttpClient http;

  AnthropicClient(Config config) {
    this.config = config;
    this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build();
  }

  LlmResponse callLlm(LlmRequest request) {
    String system = "";
    List<Map<String, Object>> messages = new ArrayList<>();
    for (ChatMessage message : request.messages()) {
      switch (message.role()) {
        case "system" -> system = message.content();
        case "user" -> messages.add(map("role", "user", "content", message.content()));
        case "assistant" -> {
          List<Map<String, Object>> blocks = new ArrayList<>();
          if (message.content() != null && !message.content().isBlank()) blocks.add(map("type", "text", "text", message.content()));
          if (message.tool_calls() != null) {
            for (ToolCall call : message.tool_calls()) blocks.add(map("type", "tool_use", "id", call.id(), "name", call.name(), "input", call.args()));
          }
          messages.add(map("role", "assistant", "content", blocks));
        }
        case "tool" -> messages.add(map("role", "user", "content", List.of(map(
            "type", "tool_result", "tool_use_id", message.tool_call_id(), "content", message.content()))));
        default -> { }
      }
    }
    JsonNode response = post(map(
        "model", config.anthropicModel(), "max_tokens", 2048, "system", system,
        "messages", messages, "tools", Prompts.TOOLS));
    StringBuilder text = new StringBuilder();
    List<ToolCall> calls = new ArrayList<>();
    for (JsonNode block : response.path("content")) {
      switch (block.path("type").asText()) {
        case "text" -> text.append(block.path("text").asText());
        case "tool_use" -> calls.add(new ToolCall(
            block.path("id").asText(), block.path("name").asText(),
            JSON.convertValue(block.path("input"), new TypeReference<>() {})));
        default -> { }
      }
    }
    return new LlmResponse(new ChatMessage("assistant", text.toString(), calls, null));
  }

  SearchPlan planSearches(String brief, int count) {
    Map<String, Object> data = structured(Prompts.planSystem(count), "Research brief:\n" + brief, Prompts.PLAN_SCHEMA, 2048);
    List<SearchItem> searches = new ArrayList<>();
    for (Object raw : list(data.get("searches"))) {
      Map<?, ?> item = (Map<?, ?>) raw;
      searches.add(new SearchItem(Database.text(item.get("query")), Database.text(item.get("reason"))));
    }
    return new SearchPlan(searches);
  }

  String webSearch(SearchItem item, int maxUses) {
    List<Map<String, Object>> messages = new ArrayList<>();
    messages.add(map("role", "user", "content", "Search query: %s\nWhy this matters: %s\n\nSearch the web and summarize the most relevant findings.".formatted(item.query(), item.reason())));
    JsonNode response = null;
    for (int i = 0; i < 4; i++) {
      response = post(map(
          "model", config.anthropicModel(), "max_tokens", 1024, "system", Prompts.SEARCH_SYSTEM,
          "messages", messages,
          "tools", List.of(map("type", "web_search_20250305", "name", "web_search", "max_uses", maxUses)),
          "output_config", map("effort", "low")));
      if (!"pause_turn".equals(response.path("stop_reason").asText())) break;
      messages.add(map("role", "assistant", "content", JSON.convertValue(response.path("content"), Object.class)));
    }
    StringBuilder summary = new StringBuilder();
    if (response != null) {
      for (JsonNode block : response.path("content")) if ("text".equals(block.path("type").asText())) summary.append(block.path("text").asText());
    }
    String body = summary.toString().trim();
    return "### " + item.query() + "\n" + (body.isEmpty() ? "(no findings)" : body);
  }

  ReportData writeReport(String brief, List<String> findings) {
    String user = "Research brief:\n" + brief + "\n\nFindings from web searches:\n\n" + String.join("\n\n", findings);
    Map<String, Object> data = structured(Prompts.WRITE_SYSTEM, user, Prompts.WRITE_SCHEMA, 2500);
    return new ReportData(Database.text(data.get("short_summary")), Database.text(data.get("markdown_report")));
  }

  private Map<String, Object> structured(String system, String user, Map<String, Object> schema, int maxTokens) {
    JsonNode response = post(map(
        "model", config.anthropicModel(), "max_tokens", maxTokens, "system", system,
        "messages", List.of(map("role", "user", "content", user)),
        "output_config", map("effort", "low", "format", map("type", "json_schema", "schema", schema))));
    StringBuilder text = new StringBuilder();
    for (JsonNode block : response.path("content")) if ("text".equals(block.path("type").asText())) text.append(block.path("text").asText());
    try {
      return JSON.readValue(text.toString(), new TypeReference<>() {});
    } catch (JsonProcessingException error) {
      throw new RuntimeException("Could not decode structured Anthropic response", error);
    }
  }

  private JsonNode post(Map<String, Object> body) {
    if (config.anthropicApiKey().isBlank()) throw ApplicationFailure.newNonRetryableFailure("ANTHROPIC_API_KEY is required", "LLMFatalError");
    try {
      HttpRequest request = HttpRequest.newBuilder(URI.create(config.anthropicMessagesUrl()))
          .timeout(Duration.ofSeconds(55))
          .header("content-type", "application/json")
          .header("anthropic-version", "2023-06-01")
          .header("x-api-key", config.anthropicApiKey())
          .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)))
          .build();
      HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
      if (response.statusCode() < 200 || response.statusCode() >= 300) {
        String message = "Anthropic returned HTTP %d: %s".formatted(response.statusCode(), response.body());
        if (List.of(400, 401, 403, 404).contains(response.statusCode())) throw ApplicationFailure.newNonRetryableFailure(message, "LLMFatalError");
        throw new RuntimeException(message);
      }
      return JSON.readTree(response.body());
    } catch (IOException error) {
      throw new RuntimeException("Anthropic request failed", error);
    } catch (InterruptedException error) {
      Thread.currentThread().interrupt();
      throw new RuntimeException("Anthropic request interrupted", error);
    }
  }

  static String json(Object value) {
    try { return JSON.writeValueAsString(value); }
    catch (JsonProcessingException error) { throw new RuntimeException(error); }
  }

  @SuppressWarnings("unchecked")
  static List<Object> list(Object value) { return value instanceof List<?> items ? (List<Object>) items : List.of(); }

  private static Map<String, Object> map(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }
}
