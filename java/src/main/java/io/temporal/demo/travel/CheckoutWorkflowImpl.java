package io.temporal.demo.travel;

import io.temporal.activity.ActivityOptions;
import io.temporal.common.RetryOptions;
import io.temporal.demo.travel.Models.CheckoutRequest;
import io.temporal.demo.travel.Models.CheckoutReservation;
import io.temporal.demo.travel.Models.CheckoutResult;
import io.temporal.demo.travel.Models.CheckoutStepRequest;
import io.temporal.demo.travel.Models.FinalizeCheckoutResult;
import io.temporal.demo.travel.Models.ItineraryItem;
import io.temporal.failure.ActivityFailure;
import io.temporal.workflow.Workflow;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class CheckoutWorkflowImpl implements CheckoutWorkflow {
  private final AgentActivities activities = Workflow.newActivityStub(AgentActivities.class,
      ActivityOptions.newBuilder().setStartToCloseTimeout(Duration.ofSeconds(30))
          .setRetryOptions(RetryOptions.newBuilder().setInitialInterval(Duration.ofSeconds(1))
              .setBackoffCoefficient(2).setMaximumInterval(Duration.ofSeconds(5)).setMaximumAttempts(3)
              .setDoNotRetry("HotelBookingFailed", "BookingDeclined").build()).build());

  @Override
  public CheckoutResult run(CheckoutRequest request) {
    List<CheckoutReservation> reservations = new ArrayList<>();
    try {
      for (String kind : List.of("flight", "hotel", "activity")) {
        for (ItineraryItem item : request.items()) {
          if (!kind.equals(item.kind())) continue;
          CheckoutStepRequest step = new CheckoutStepRequest(request.account_key(), item);
          reservations.add(switch (kind) {
            case "flight" -> activities.bookFlight(step);
            case "hotel" -> activities.bookHotel(step);
            default -> activities.bookActivity(step);
          });
        }
      }
      FinalizeCheckoutResult booking = activities.finalizeCheckout(request);
      return new CheckoutResult("booked", "Checkout completed and every itinerary item is booked.",
          Workflow.getInfo().getWorkflowId(), reservations, List.of(), null, booking.booking_id());
    } catch (ActivityFailure failure) {
      List<CheckoutReservation> reversed = new ArrayList<>(reservations);
      Collections.reverse(reversed);
      List<CheckoutReservation> compensations = new ArrayList<>();
      for (CheckoutReservation reservation : reversed) {
        compensations.add(switch (reservation.kind()) {
          case "flight" -> activities.cancelFlight(reservation);
          case "hotel" -> activities.cancelHotel(reservation);
          default -> activities.cancelActivity(reservation);
        });
      }
      String cancelled = compensations.isEmpty() ? "no prior reservations" : String.join(", ", compensations.stream().map(CheckoutReservation::title).toList());
      String message = rootMessage(failure);
      return new CheckoutResult("compensated", "Checkout stopped: " + message + " Compensation completed: cancelled " + cancelled + ".",
          Workflow.getInfo().getWorkflowId(), reservations, compensations, message, null);
    }
  }

  private static String rootMessage(Throwable error) {
    while (error.getCause() != null) error = error.getCause();
    return error.getMessage() == null ? "Checkout failed." : error.getMessage();
  }
}
