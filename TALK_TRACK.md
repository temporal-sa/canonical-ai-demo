# Demo Run Script: Temporal owns the ReAct loop

A word-for-word script for the Greece demo (Athens, Santorini, Mykonos). Each
beat is **Tell** (say this), **Show** (do this), **Tell** (say this). The spoken
lines are in quotes so you can practice off them directly.

---

## Before you start

```bash
make up
```

- Chat UI at [http://localhost:8000](http://localhost:8000), Temporal UI at [http://localhost:8233](http://localhost:8233). Put them side by side.
- Have a terminal ready for the crash beat (`make kill-worker` and `make worker`).
- Stay on the seeded rails: fly from New York on Oct 3, 2026. Greece is fully built out
(Athens, Santorini, Mykonos) with real hotels, sights, and island flights. Destination
research is live web search, so any place works there.

---

## 1. One turn of the loop

**Tell:**

> "The big idea I want to land today is really simple. An AI agent is just a loop. The
> model looks at what you asked, it decides to call a tool, it looks at the result, and it
> answers. That's the whole thing. What makes it interesting is what Temporal does around
> that loop. So let me start with the simplest possible version."

**Show:** type

```
Find me flights from New York to Athens on October 3rd.
```

**Tell:**

> "So I just asked in plain English, and the model decided on its own to call our flight
> search tool, it got the results back, and it wrote that answer. That is one turn of the
> loop. Now here's the part that matters. This whole chat is actually a Temporal workflow
> running behind the scenes. If I click this workflow ID up here, it opens that workflow in
> Temporal, and look, every step is right here in the history. The model call, the tool
> call, the result. So the model calls are activities, the tools are activities, and the
> loop itself is the workflow. You get this whole history for free, and it doubles as the
> agent's memory."

---

## 2. The loop iterates

**Tell:**

> "That was one tool call. But most real requests need a few. So let me give it something
> it has to break down into steps."

**Show:** type

```
Now find a well-located 4-star hotel in Athens for four nights, and a couple of must-see sights.
```

**Tell:**

> "So one sentence from me turned into two separate tool calls. It searched hotels, it
> searched things to do, and then it pulled the answer together. I never told it the order,
> or which tools to use. It worked that out. And if you look back at the history, both of
> those calls are sitting right there under this one turn, each recorded on its own."

---

## 3. Build the itinerary

**Tell:**

> "Now let's actually start building the trip. Keep an eye on the panel over on the left
> while I do this."

**Show:** type

```
Perfect, add those to my itinerary.
```

**Tell:**

> "There we go. The flight, the hotel, and both sights just dropped into the itinerary on
> the left. And here's what I want you to notice. That itinerary is not sitting in a
> database, or a cache, or a shopping cart table somewhere. It is just state inside the
> workflow. So if the worker died right now, it would come back with all of this exactly as
> it is. Nothing lost."

---

## 4. Deep research, in parallel, and it survives a crash

**Tell:**

> "Okay, this is my favorite part. So far every step has been a quick little tool call. But
> sometimes you want the agent to go do some real homework. I'm thinking about tacking on a
> few days in the islands, but honestly I don't know how I'd spend them. So I'm going to
> have it do a deep dive."

**Show:** type

```
I'm also thinking about a few extra days in the Greek islands. Do a deep dive on how to spend a few days in Santorini and Mykonos.
```

**Tell:**

> "So what's happening now is a bit different. This isn't one tool call. Under the hood it
> planned out a handful of web searches, and it's running all of them at once, live against
> the web, and then it'll write the whole thing up. Jump over to Temporal for a second. See
> all these search activities firing off in parallel? Now here's the fun part. I'm going to
> kill the worker right in the middle of this."

**Show:** run

```
make kill-worker      # wait a beat, then:
make worker
```

**Tell:**

> "And it just picks right back up. The searches that already finished stay finished, they
> don't run again, and only the ones that hadn't come back get retried. I did not write a
> single line of retry logic or recovery code for that. That is all Temporal. In plain
> Python you'd be hand rolling async tasks, tracking which ones finished, and figuring out
> how to resume after a crash. Here it's basically one line."

**Then, once the guide lands, say:**

> "Alright, that gave me a really good feel for it. So let me add those island days to the
> trip."

**Show:** type

```
Love it, add a few days in Santorini and Mykonos to my itinerary.
```

**Tell:**

> "And it just built out both legs for me. It found the island hop flights, it picked the
> hotels, it added a couple of things to do on each island, and it dropped all of it into
> the plan. So the trip on the left is now a full multi city itinerary, and I never had to
> spell any of it out."

---

## 5. The provider goes down

**Tell:**

> "Now let me show you what happens when things go wrong, because in the real world the
> model provider goes down all the time. I'm going to open demo controls up here and flip
> this switch to simulate the LLM being unavailable."

**Show:** open **Demo controls** (top right), flip **LLM API** off, then type

```
Great, now pull the whole thing into a day-by-day plan across Athens, Santorini, and Mykonos.
```

**Tell:**

> "So it's just sitting there thinking, because this turn needs the model, and the model is
> down. But notice, the app didn't crash, and nobody got an error. If I pop over to
> Temporal, you can see it's retrying that call, over and over, backing off each time. Now
> watch what happens when I bring it back."

**Show:** flip **LLM API** back on.

**Tell:**

> "And there's the answer. The very next retry just went through, and the person using this never saw a thing. The unreliable parts of an agent, the model and the tools, are all activities, and Temporal retries them for me. That is one line of config, not custom retry logic that I had to build."

---

## 6. Book it, with a human in the loop

**Tell:**

> "Okay, the trip looks great. Let me go ahead and book it. And this is the human in the
> loop moment."

**Show:** type

```
This looks perfect, book the whole trip.
```

**Tell:**

> "So instead of just charging ahead and booking, it stops and asks me to confirm. And here's the neat part. Right now, over in Temporal, this workflow is paused. It's not burning a thread, it's not holding a connection open, it's just sitting there waiting on a person. It could wait like this for a minute, or for thirty days, and it costs basically nothing. So when I click confirm, that sends a signal into the workflow, and it wakes up right where it left off and finishes the booking."

**Show:** click **Confirm**.

**Tell:**

> "And it's booked. The itinerary clears out, and we're done."

---

## 7. Knowing what not to retry (optional)

**Tell:**

> "One more quick one. I told you Temporal retries things that fail. But some failures
> should not be retried, and it knows the difference. Watch what happens if I try to book
> that same flight a second time."

**Show:** type

```
Actually, add that Athens to Santorini flight again and book it.
```

**Tell:**

> "And it comes right back and says that flight's already in the trip, it's not going to
> book it twice. That's a business rule, not a glitch. So compare that to the outage a
> minute ago. That was temporary, so Temporal just kept retrying until it recovered. This
> one is never going to succeed, no matter how many times you try, so it fails fast and the
> agent just explains it. And that difference is one flag on the error.
>
> And that's really the whole point. It was the same simple loop the entire way through.
> And Temporal quietly handled the flaky provider, the parallel research, a full on crash,
> a long pause waiting on a human, and a failure it knew not to retry. And I never once had
> to write the resilience code myself."

---

## Reset between runs

- A new conversation, or just refreshing the page, gives you a fresh workflow.
- The itinerary, the bookings, and the LLM toggle are all per conversation, so they reset
on their own. Nothing to restart between demos.

## If a prompt stalls

- No flights or hotels found: you're off the seeded rails. Stay with New York, Oct 3, and
Athens / Santorini / Mykonos.
- "That airline isn't available": the model won't invent flights, so just say "the cheapest one."
- If a query hangs, run `make status`, and if the worker is down, `make worker`.

> **Shorter alternate opener (travel for an event):** "I'd like to travel for an event." then
> "Athens in September", which finds real events, then flights, then an invoice. It's a
> quicker, goal-driven version that mirrors the original Temporal AI Agent.

