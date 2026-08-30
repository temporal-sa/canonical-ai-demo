package main

import (
	"context"
	"log"

	"github.com/temporal-sa/canonical-ai-demo/go/internal/travelagent"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func main() {
	cfg := travelagent.LoadConfig()
	temporalClient, err := travelagent.DialTemporal(cfg)
	if err != nil {
		log.Fatalf("connect to Temporal: %v", err)
	}
	defer temporalClient.Close()

	db, err := travelagent.NewDB(context.Background(), cfg.DBURL)
	if err != nil {
		log.Fatalf("configure Postgres: %v", err)
	}
	defer db.Close()

	activities := travelagent.NewActivities(cfg, db, temporalClient)
	w := worker.New(temporalClient, cfg.TaskQueue, worker.Options{})
	w.RegisterWorkflowWithOptions(travelagent.TravelAgentWorkflow, workflow.RegisterOptions{Name: "TravelAgentWorkflow"})
	w.RegisterWorkflowWithOptions(travelagent.CheckoutWorkflow, workflow.RegisterOptions{Name: "CheckoutWorkflow"})
	w.RegisterActivityWithOptions(activities.CallLLM, activity.RegisterOptions{Name: "call_llm"})
	w.RegisterActivityWithOptions(activities.ExecuteTool, activity.RegisterOptions{Name: "execute_tool"})
	w.RegisterActivityWithOptions(activities.PlanSearches, activity.RegisterOptions{Name: "plan_searches"})
	w.RegisterActivityWithOptions(activities.WebSearch, activity.RegisterOptions{Name: "web_search"})
	w.RegisterActivityWithOptions(activities.WriteReport, activity.RegisterOptions{Name: "write_report"})
	w.RegisterActivityWithOptions(activities.BookFlight, activity.RegisterOptions{Name: "book_flight"})
	w.RegisterActivityWithOptions(activities.BookHotel, activity.RegisterOptions{Name: "book_hotel"})
	w.RegisterActivityWithOptions(activities.BookActivity, activity.RegisterOptions{Name: "book_activity"})
	w.RegisterActivityWithOptions(activities.CancelFlight, activity.RegisterOptions{Name: "cancel_flight"})
	w.RegisterActivityWithOptions(activities.CancelHotel, activity.RegisterOptions{Name: "cancel_hotel"})
	w.RegisterActivityWithOptions(activities.CancelActivity, activity.RegisterOptions{Name: "cancel_activity"})
	w.RegisterActivityWithOptions(activities.FinalizeCheckout, activity.RegisterOptions{Name: "finalize_checkout"})

	log.Printf("go worker polling task queue %q on %s (namespace: %s, provider: %s)", cfg.TaskQueue, cfg.TemporalClientOpts.HostPort, cfg.TemporalClientOpts.Namespace, cfg.LLMProvider)
	if err := w.Run(worker.InterruptCh()); err != nil {
		log.Fatalf("worker stopped: %v", err)
	}
}
