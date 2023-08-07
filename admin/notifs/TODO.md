# Admin Notifications

Going to need a _lot_ of visibility into push notifications in order to
facilitate reliable delivery.

# Data Points

This section describes singular data points that we want to get a pulse
check on the health of our push notifications flow

## Push Tokens

- [ ] Number of (believed to be) active push tokens

## Push Tickets

Sending a messages works like this:

- Message is put on the redis list To Send queue with retries: 0
- A recurring job (Send Job) regularly checks the queue (about once per minute),
  batches the notifications and sends. While the job is working on
  a ticket, its moved to the Purgatory set.
- Failures return to the To Send queue if the new retries counter
  is below a threshold

- [ ] Number of queued message attempts (length of To Send)
- [ ] Number of working message attempts (length of Purgatory)
- [ ] Oldest queued at (the retriedAt or createdAt of the oldest
      message attempt in To Send)
- [ ] Last time the Send Job was run (started at)
- [ ] Running time of last Send Job
- [ ] Number of messages attempted during last Send Job

## Push Receipts

Push tickets work like this:

- Successful message attempts are added to the redis list Push Receipt Cold Set with retries: 0
- A recurring job (Push Receipt Cold to Hot Job) regularly checks the Push
  Receipt Cold Set (about once per 5 minutes). It moves any receipts from the
  Push Receipt Cold Set to the Push Receipt Hot Set which are at least 15m old
- A recurring job (Push Receipt Check Job) regularly checks the Push Receipt Hot
  Set (about once per minute). It batches receipts. Those in a final state
  (error or ok) are catalogued and removed, those in a transient state (pending)
  will be added to the Push Receipt Cold Set if the new retries is below a
  threshold

  While the job is working on a push receipt in the Hot Set its temporarily moved to
  a Push Receipt Purgatory to ensure it doesn't get lost if the instance dies

- [ ] Number of queued receipts (length of Push Receipt Cold Set)
- [ ] Number of overdue receipts (length of Push Receipt Hot Set)
- [ ] Oldest due time in Push Receipt Cold Set (is the job to move it to the Hot Set delayed?)
- [ ] Oldest due time in Push Receipt Hot Set (is the job to check hot receipts delayed?)
- [ ] Number of pending receipts (length of Push Receipt Purgatory)
- [ ] Last time Push Receipt Cold to Hot Job was run (started at)
- [ ] Running time of last Push Receipt Cold to Hot Job
- [ ] Number of receipts moved during last Push Receipt Cold to Hot Job
- [ ] Last time Push Receipt Check Job was run (started at)
- [ ] Running time of last Push Receipt Check Job
- [ ] Number of push receipts checked during last Push Receipt Check Job

# Histograms

This section describes histograms which are primarily intended to recognize if
any long-term trends change (e.g., deleting a lot more push tokens than
expected). All values are as of 11:59:59.999pm on the day, but are not frozen
until 4am the following day (to account for events which have an earlier
timestamp as their relevant time, e.g., push ticket creations are bucketed by
message attempt start)

## Push Tokens

1. [ ] Number of completely new push tokens by day
   - Client sent us a push token we didn't have
2. [ ] Number of reassigned push tokens by day
   - Client sent us a push token we already had, but for a new account
3. [ ] Number of push tokens refreshed by day
   - Client sent us a push token we already had & was already assigned to
     that person
4. [ ] Number of deleted push tokens due to user account deletion per day
5. [ ] Number of deleted push tokens due to DeviceNotRegistered tickets per day
6. [ ] Number of deleted push tokens due to DeviceNotRegistered receipts per day
7. [ ] Number of push tokens per day (should match 1 - 3 - 4 - 5)

## Push Tickets

1. [ ] Message attempts started by day
2. [ ] Push ticket initial attempts by day (timestamp is message attempt start)
3. [ ] Push ticket retries by day (timestamp is message attempt start)
4. [ ] Push ticket creation successes by day (timestamp is message attempt start)
5. [ ] Push ticket creation failures by day (timestamp is message attempt start)
6. [ ] Push ticket creations abandoned by day (timestamp is message attempt start)
   - This is specifically referring to giving up because the retry counter was too
     high, not because of a permanent failure

## Push Receipts

1. [ ] Push receipts requested by day
2. Push receipt results (timestamp is push receipt attempt start):
   a. [ ] DeviceNotRegistered
   b. [ ] MessageTooBig
   c. [ ] MessageRateExceeded
   d. [ ] MismatchSenderId
   e. [ ] InvalidCredentials
   f. [ ] Pending
3. [ ] Push receipts requeued by day (timestamp is push receipt attempt start)
4. [ ] Push receipts abandoned by day (timestamp is push receipt attempt start)
       (exceeded max retries)
