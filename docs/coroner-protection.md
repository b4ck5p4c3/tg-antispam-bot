# Coroner protection

Coroner has one reference account. Confirmed deletion candidates enter a persisted,
user-wide quarantine before any removal. The default delay is 60 minutes. A candidate
stores membership generations for every target chat, so approval cannot silently apply
to a later rejoin or another chat. Profile links use `tg://user?id=...` and the numeric
ID remains visible when a deleted profile cannot be opened.

## Rules and initial thresholds

- New candidates: count unique users detected today per grade; compare with the mean
  of the previous seven complete calendar days, excluding today. Trigger at
  `max(minimum users, ceil(multiplier * mean))`. Every grade starts with multiplier
  3 and minimum 5. A user's first candidate event in a calendar day is counted once;
  its detection grade is fixed for historical comparison. The user's current global
  grade continues to advance normally and is shown separately.
- Deleted profiles: at least 20 unique users with a determinate result in 30 minutes;
  trigger at 80% false results. Evaluated globally and per moderated chat. Latest
  determinate results deduplicate users across repeated checks and chats. Reference
  lookups and secondary profile confirmations do not increase this trigger sample.
- Recently alive transitions: in 30 minutes, at least 20 recently alive checked users,
  at least 5 negative matches, and a 50% negative ratio. Recently alive means a
  successful check or actual new message within the previous 24 hours.
- API failures: at least 20 background profile API calls in 5 minutes, at least 5
  failures, and a 50% failure ratio. Reference and UI requests are excluded.
- Incomplete/contradictory profiles: at least 20 unique users in 30 minutes, at least
  3 indeterminate profiles, and a 20% indeterminate ratio. These results never count
  as confirmed deletions.
- Candidate activity: the first actual new message sent by a candidate after detection
  cancels that candidate, starts its cooldown, and blocks all automatic quarantine
  releases. A new contradiction invalidates existing approval grants immediately.
  Forwarded attribution, service join messages and edits of older messages do not
  provide this activity evidence.

All thresholds and windows below are editable. A rule with too few observations is
explicitly labelled disabled for insufficient data. Missing calendar-day coverage is
not treated as zero candidates. Only observed zero days contribute a zero to the mean.
Coverage is accumulated while checks are running, with configurable tolerance for
maintenance gaps and a configurable required daily coverage percentage (default 100%).
Restart gaps and stopped periods remain missing coverage. Changing calendar timezone
invalidates calendar comparison data and metric rollups, without resetting quarantine,
removal budgets or incidents.

## Manual review and notifications

An anomaly latches a module-wide removal block. The module may still report `running`:
ordinary checks and observation continue; **Protection: blocked** reports the independent
removal gate. `/coroner stop` still stops all profile checks, including approved work.
A reference failure separately puts the module in `error` and requires a successful
manual start. Restart always preserves protection and returns a running module to stopped.

Existing `/as_service` subscribers are notified only after rechecking their administrator
rights in every moderated chat. The module edits its existing review notification at the
configured interval. Every notification, authorization lookup and UI operation shares
Coroner's Telegram RPM budget. Failed notification delivery does not release protection.

`/coroner review` and the notification buttons expose a snapshot with exact candidate
IDs and target membership generations. Account lists and target chats have pagination;
selections belong to the administrator who made them. Approve selected accounts or the
whole snapshot, reject the snapshot, or request fresh checks. Rechecks grant no approval.
A new snapshot supersedes a pending one. New candidates or new memberships do not gain
permission from an earlier snapshot. A fresh incident invalidates previous grants.
Approval expires after the configured lifetime and never shortens the quarantine delay.
Outside an incident, **Pause removals and review** explicitly latches the removal gate
before creating a manual snapshot. Merely browsing the quarantine does not pause it.

If some accounts remain after a decision, create a new snapshot to review them. Rejected
or freshly alive candidates return to ordinary monitoring with a configurable cooldown
against immediate recreation. After quarantine is empty and current detector conditions
have cleared, `/coroner acknowledge` explicitly releases the safety incident. Start,
stop, reference changes, expiry of temporary errors and process restarts never release it.
A budget violation still blocks the next deletion even after an acknowledgement.
Safety gates are rechecked immediately before issuing a removal. An already-issued
Telegram request may still complete after a block; its reservation remains charged.

## Persisted removal budgets

Each rolling window enforces all four limits: chat count, chat percentage, global count,
and global percentage. A single user removed from three chats consumes three units.
The effective allowance is `min(count limit, floor(population * percent / 100))`.
There is no rounding upward for small chats: 5% of 10 members permits zero removals.

Initial short-window limits are 2 per chat and 5 globally in 10 minutes, each additionally
bounded by 5% of memberships. Initial daily limits are 5 per chat and 10 globally,
additionally bounded by 10%. Adjust these settings for the intended chat populations.
Global population sums chat memberships. Counts are fetched through the shared RPM
budget and cached for the configured lifetime. The minimum observed population among
current counts and active reservations supplies the percentage denominator, preventing
growth in the reported population from inflating an already active budget.

The module atomically saves a reservation before attempting removal. Pending requests
consume budget even if they wait longer than the window. A successful or uncertain
request is charged conservatively from the time its outcome is received. A definite
Telegram rejection or a guard cancellation before dispatch releases the reservation.
A lost response remains charged and creates an incident; a pending reservation found
after restart becomes uncertain and is charged from recovery time. Member-count failure
blocks removal. Manual approval cannot bypass any of these limits.

Reservations are retained for at least the configured retention, removal statistics
period and longest budget window. If a later configuration extends a window into a
period whose reservation data was discarded, automatic removals block for insufficient
budget history. Budget evidence is never replaced with invented zero counts.

Dry run uses the same quarantine, checks, incidents and virtual reservations, and logs
intended removals. It sends no kick requests and adds no actual removal-history entries.
Virtual reservations constrain dry runs; switching to real mode does not charge virtual
operations against the actual budget.

## Statistics

`/coroner` and its Update button show the module-wide summary in private chats or
moderated groups. Detectors, Quarantine and Review removals open dedicated pages.
All commands and buttons require current administrator rights in every moderated chat.

Detector pages show settings, sample availability, current check counts, raw false and
unknown counts, deduplicated trigger samples, percentages, effective thresholds and
progress toward triggering. Candidate rules show current quarantine occupancy and new
daily candidates separately. An insufficient sample disables that rule explicitly;
other rules and mandatory removal limits continue to apply.

Minimum, maximum and mean are calculated over recorded snapshots in the configured
number of calendar days including today. Percentage means also report the weighted
`sum(matches) / sum(samples)`. Sampling interval is configurable. Daily compact rollups
retain ranges and sums rather than every historical point. Missing percentage samples
are excluded instead of becoming zeros. Changing a rule's window prevents comparisons
against observations recorded for a different window.
Incident trigger values are captured immediately. Views include the live current
observation in the displayed ranges without changing historical storage.

Additional pages show quarantine readiness and oldest age, cancellations confirmed
alive, live-message settings, approval expiry and cooldown, budgets and their usage,
and removals for the configured statistics period (7 days by default). Removal
statistics show unique user counts plus chat-removal counts; percentages use current
summed chat memberships. The existing 30-day module totals remain available.

Quarantine, review decisions, detector observations, calendar coverage, budget evidence
and latched reasons live in `coroner_state.json`. Human-readable temporary errors remain
in memory only, at most five for seven days. Latched reasons are separate protection
state and remain visible even after those temporary errors expire.

## Configuration

The following `protection` object is added automatically to valid existing
`coroner_config.json` files. Edit settings while stopped, then start to reload.
Existing candidate deadlines and approval expiry timestamps retain the values assigned
when those records were created; duration changes apply to new records.

```json
{
  "protection": {
    "quarantine_seconds": 3600,
    "recheck_seconds": 300,
    "approval_seconds": 7200,
    "rejection_cooldown_seconds": 86400,
    "candidate_history_days": 7,
    "candidate_coefficients": {
      "G1": 3.0,
      "G2": 3.0,
      "G3": 3.0,
      "G4": 3.0
    },
    "candidate_minimum_users": {
      "G1": 5,
      "G2": 5,
      "G3": 5,
      "G4": 5
    },
    "day_timezone": "UTC",
    "minimum_day_coverage_percent": 100,
    "maximum_collection_gap_seconds": 30,
    "false_results": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 1,
      "threshold_percent": 80
    },
    "recent_alive_seconds": 86400,
    "alive_transitions": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 5,
      "threshold_percent": 50.0
    },
    "api_errors": {
      "window_seconds": 300,
      "minimum_calls": 20,
      "minimum_failures": 5,
      "threshold_percent": 50
    },
    "profile_inconsistencies": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 3,
      "threshold_percent": 20.0
    },
    "activity_minimum_users": 1,
    "activity_window_seconds": 1800,
    "metric_sample_seconds": 300,
    "metric_history_days": 7,
    "removal_statistics_days": 7,
    "notification_interval_seconds": 300,
    "member_count_cache_seconds": 60,
    "review_page_size": 5,
    "detector_page_size": 3,
    "resolved_request_retention_days": 30,
    "reservation_retention_days": 30,
    "removal_limits": [
      {
        "name": "short",
        "window_seconds": 600,
        "chat_count": 2,
        "global_count": 5,
        "chat_percent": 5.0,
        "global_percent": 5.0
      },
      {
        "name": "daily",
        "window_seconds": 86400,
        "chat_count": 5,
        "global_count": 10,
        "chat_percent": 10.0,
        "global_percent": 10.0
      }
    ]
  }
}
```
