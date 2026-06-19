# How a WhatsApp Rant Turned Into InternPilot

It didn't start as a project. It started as a guy in a school friend group chat being annoyed about a rejection email.

This was sometime before the AI Club had even put out the buildathon themes. We were both home for the break, doing the usual nothing-in-particular thing you do on vacation - half-watching something, half on the phone. A friend from school - not someone at DAU, he's at a different college entirely, we just never left the group chat that's been running since class 12 - had just gotten a rejection mail for something he'd applied to that same afternoon. Not the next day. The same afternoon. He sent a screenshot with one line: "bro didn't even let it sit overnight."

Nobody really replied properly. A couple of laughing emojis, somebody said "HR be like that," and the chat moved on to something else entirely. That's usually how these things go - everyone's been there, everyone vents for two minutes, and then everyone goes back to whatever they were half-watching.

I didn't do anything about it at the time. It just sat there.

## The first plan, and why it was wrong

The AI Club dropped the theme list for the 7-day buildathon a few weeks later, and like pretty much everyone in our batch, we spent a solid two days going back and forth on what to build. We had a Notion page (badly organised, half the entries crossed out by the next morning) with ideas ranging from a GPA calculator nobody had asked for to some kind of DBMS-assignment helper, because both of us were neck-deep in DBMS coursework around then and everything looked like a database problem.

It was during one of those late discussions that someone brought up the rejection-mail screenshot from weeks earlier. Half-joking, like "what if we actually built something for that." And then it just sat in the conversation a second longer than a joke usually does.

We didn't commit to it immediately. We called a couple of seniors who'd been through a few of these buildathons before - people who could tell us honestly whether an idea was a real seven-day scope or just a fun thing to say in a pitch. The first version we floated wasn't even close to what InternPilot ended up being. The plan was basically: pull job listings from a bunch of different sources - Greenhouse, Lever, Ashby, a couple of aggregator boards - dump them into one database, and let students search across all of it instead of checking five tabs separately. More listings, one place.

One of the seniors asked a question that we didn't have a good answer for: "okay, but once you've got five thousand listings in one place, how does a student know which forty to actually apply to?" We didn't have an answer. We'd basically built a bigger pile, not a better pile.

That conversation is the actual reason InternPilot exists in the form it does. Not "more listings." Filtering and ranking the listings that already exist, so a student isn't drowning in them.

## What broke first, once we actually looked

Once we started pulling real postings to test the ingestion code, one of us started manually spot-checking a handful of them out of curiosity more than anything else. Several looked completely normal - real company name, specific-sounding role, a reasonably detailed description — but searching around for any sign the company was actually hiring for that role right now turned up nothing. No recent activity. Postings that had clearly been live for sixty, ninety days, still sitting there, still being served to anyone searching.

This is a documented thing, not something we discovered - researchers studying job boards have put the number of effectively dead postings somewhere in the 20–30% range at any given time, for a mix of reasons: pipeline-building, internal process artifacts, or just nobody bothering to take the listing down. But seeing it on our own pulled data, instead of reading it as a statistic in some article, changed how we thought about the rest of the week. We weren't just building a ranking tool anymore. We needed something that could flag a listing as probably dead *before* a student spent an evening writing a cover letter for it.

That became its own module, separate from matching entirely - score every posting for "is this even real" before it's allowed to show up in a feed at all.

## Building a profile that isn't just a PDF

The harder problem, honestly, was the other side - representing the student, not the listing. A resume is text. It doesn't tell software that "built a pipeline using Pandas" and a job asking for "data manipulation experience" mean almost the same thing, because they don't share a single word in common.

Our first pass was keyword overlap - extract skills from the resume, extract requirements from the posting, count matches. It was bad in an embarrassing way. It missed obvious matches because the wording didn't line up, and it occasionally matched things that shouldn't have, because two unrelated terms happened to share a word.

We switched to comparing things using sentence embeddings instead. The idea, stripped of jargon: you run a piece of text through a small model and get back a list of numbers - in our case, 384 of them - that represents roughly where that text sits in some abstract space of meaning. Two pieces of text that mean similar things end up with similar numbers, even if the actual words are completely different. You can then just measure distance between a profile's numbers and a posting's numbers and use that as a similarity score.

We picked a small model that runs locally instead of calling an API for every embedding - partly because we were burning through free-tier limits fast enough already, and partly because there's something nice about not depending on a network call just to compare two pieces of text. The first time we ran it against an actual resume - one of our own, not a sample one - and saw it correctly line up "built data pipelines" with a posting asking for "ETL experience," neither of which share a word, that was the point it stopped feeling like a checkbox feature and started feeling like the thing the whole project was actually about.

## When the AI started making things up

This is the part that worried us more than any bug did.

We were generating draft cover letters from a resume plus a job description, and one of the early test outputs confidently listed a skill that was nowhere in the source resume. It wasn't garbage text. It read completely normally - fluent, specific, plausible. Which is exactly the problem. If you weren't actively checking, you'd never catch it, and neither would the recruiter reading it, until an interview question exposed it.

We ended up building a check that runs after every generation: take every concrete claim in the draft and verify it against the actual profile - the resume text, the listed skills, the project descriptions. If something in the draft isn't backed up by anything in the source data, it gets flagged, and the model gets sent back with an explicit instruction not to claim that specific thing, and tries again. There's a cap on how many times it'll retry before we just show the user what's left.

It cost us a chunk of an evening we'd planned to spend on the frontend instead. But shipping a tool that quietly invents things on your resume felt like a worse outcome than being a few hours behind.

## The unglamorous stuff that almost broke the demo

None of this is the exciting part of the writeup, but it's the part that decides whether your demo actually runs on the day.

We were burning through the free tier of whichever LLM provider we were using within hours of starting real testing — two people testing constantly on the same key does that fast. So we ended up chaining several providers together: try the first, and if it's rate-limited or times out, fall through to the next one automatically, all the way down to a local model as a last resort. It's not elegant, but it meant a single provider having a bad afternoon didn't take the whole pipeline down with it.

Auth was the other thing that ate more time than it should have. We wanted both plain email/password and Google sign-in, and the moment you support both, you get questions you didn't think to ask up front - what happens if someone signs up with email and later tries Google with the same address, what happens if a token expires mid-session, what the frontend should do if a token refresh silently fails. None of these are hard individually. There were just more of them than we expected, and we found at least one of them - the kind where a perfectly normal-looking flow leaves a user signed in with no actual data behind them - only by deliberately trying to break our own login flow late one night and noticing the second screen was just empty.

## Putting an actual number on "ghost"

Once we knew ghost postings were the real problem, we didn't want to just eyeball it. We landed on five separate signals, each weighted, combined into a single score: how old the posting is (a step function - practically zero risk in the first two weeks, climbing hard past a month, near-certain past ninety days), whether the same posting shows up across multiple job boards (one sighting contributes nothing, but a second board appearance is a real signal that something's being recycled rather than actively managed), how vague the description itself reads (word count, how many actual requirements are listed versus generic pipeline language, whether it names specific tools or just buzzwords), the company's own track record across its other postings, and - once we have enough of it - whether people from our own user base who applied to that company ever heard back at all.

We picked a threshold above which a posting gets flagged as likely dead, and tuned it against listings we'd manually checked by hand. It's not a perfect model. It's a rule-based one, deliberately - no LLM call needed to compute it, which also meant it was fast enough to run on every single posting before it's allowed into anyone's feed, instead of being a slow afterthought.

## The cohort thing nobody asked us to build

This is the feature neither of us had planned, and it came out of looking at our own test data more than any grand insight.

As we started generating fake application-outcome pairs to test the pipeline against, a pattern showed up that wasn't part of the ghost-detection logic at all. A handful of companies had postings that looked completely fine by every individual signal - recent, specific, well-written, only seen on one board. But across every simulated application to that company, the response rate sat at basically zero.

That's a different kind of dead than a ghost posting. It passes every rule-based check. The listing itself isn't fake. The company just doesn't respond, consistently, regardless of who applies.

So once enough applications have gone to the same company - we picked five as the threshold, since anything smaller felt too noisy to trust - the aggregate response rate starts feeding directly into how that company's postings get ranked. Not who applied, not what they sent, just the count and the outcome. A posting can look like a ninety-percent semantic match and still drop in the feed with a plain note explaining why: the company's last several applicants never heard back, regardless of how strong they looked on paper.

## Grading ourselves honestly

The part we're most careful about, because it would be very easy to fudge, is whether any of this is actually working.

Every time the matching engine scores a posting, that prediction - how likely a response is, whether it's a ghost - gets saved at that moment, before any real outcome exists. Later, once an outcome actually comes in, we compare the saved prediction against what really happened. Nothing gets re-scored after the fact. That ordering is the whole point - otherwise it's trivially easy to make a system look smarter than it is by quietly grading on data it's already seen.

We also run a stricter version of this: sort every prediction-outcome pair by when it happened, hold out the most recent slice as a fixed test set that never gets trained on, and train a small calibration model on growing chunks of the older data, checking accuracy against that same fixed holdout each time. If the system is actually learning anything, that accuracy should improve as the training chunk grows. We added a hard check in the code that refuses to run if the training and test data ever overlap - not a warning, an assertion that stops the whole process.

On our seed data - a few hundred simulated application-outcome pairs, nowhere near real usage - the honest number for how good the system's predictions are isn't something we're going to round up to sound impressive. It's a modest score, decent on the larger chunk of data and visibly weaker on the smaller one, which is at least the direction you'd want to see. We'd rather show that number as-is than not show one at all.

## What we cut

By day six we pulled out a feature we'd actually finished - a module for generating interview prep material based on the job description and the candidate's profile. It worked. It just didn't connect cleanly to anything else we'd built, and it was eating review time we needed for testing the parts that actually mattered to the core idea.

That one stung a bit, not going to lie. But the senior who told us to scope down hard was right. Shipping fewer things that are properly checked beats shipping more things that might fall over during a demo.

## The day it almost fell apart

Somewhere around day five, with most of the core pieces working individually, we tried running the whole thing end to end for the first time - signup through to seeing a ranked feed - and it just hung. Not an error, not a crash. It sat there loading.

We spent a couple of hours convinced something fundamental was broken in how we were handling database connections under the async setup we'd built everything on - two parts of the code each waiting on something the other one held, neither willing to let go. It's the kind of bug where the code looks completely reasonable line by line and only breaks under one specific sequence of events.

We found it. It was a small fix, in the end, much smaller than the panic suggested it should be. But for about two hours that evening, with two days left, it genuinely felt like the whole thing might not come together in time.

## What we'd do differently

Build the self-grading part earlier, honestly. We built it last, after the ranking and generation pieces were mostly done, and it would have been more useful the other way around - having a clear way to measure whether a change actually helped, instead of relying on "this looks better to me," would have saved some arguments and probably some wasted hours.

We'd also take the async side of the stack more seriously from day one instead of treating it as regular Python with extra keywords. The deadlock we hit wasn't really about ignorance of the syntax - it was about not having built intuition yet for how things actually execute under the hood. That intuition takes time to build, and we were building it under deadline pressure instead of ahead of it.

## Where it goes from here

None of this came from a feature brainstorm or a market gap we went looking for. It came from one annoyed message in an old school group chat that nobody, including us, took seriously for a few weeks. The buildathon gave us a deadline. A couple of phone calls with seniors who'd actually built things under similar pressure before kept us from spending all seven days on the wrong version of the idea. The actual problem came from someone we've known since school, refreshing his inbox on a normal afternoon, same as a lot of people that season.

There's a lot we still don't do. We can tell a student that a company has historically had a low response rate; we can't yet tell them whether their specific profile would have beaten that average. That needs more real outcome data than seven days, or honestly more than our current user base, can give us.

But if it stops even a few people from spending an evening writing a cover letter for a posting that was never going to reply, that's a fine outcome for a week's work.

— built for the DAU AI Club buildathon
