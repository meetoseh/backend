# journey_event_fenwick_trees

This table is entirely calculable from the `journey_events` table, and is used
specifically to allow calculating certain relevant totals in logarithmic time
rather than linear time. This is stored in the database to avoid the complexity
of keeping a cache in sync without risking inconsistency and a particularly bad
case of "cache miss storm" due to the expensive nature of filling that cache and
the odds all the caches will miss at the same time.

Specifically, in order to smoothly handle clients reconnecting mid-session to
the websocket server, the websocket server needs to be able to query the total
number of users, likes, and the like for a journey at a given journey time.

Without this table, getting the true data would necessarily be done with
COUNT(\*) filtering by event type and journey time. This is at least O(m)
where m is the count, though would likely be O(mlog(n)^p) at least, where p>=2. If
done without a cache, this would mean that if a webserver died, then a bunch of
clients reconnecting would each cause a superlinear query, which could easily
cripple the database. Even with a cache, even normally very minor mistakes
could get out of control quickly.

With this table, the totals can be calculated in O(log(n)log(m)) where n is the
total number of journey events and m is number of bins for the journey, at the
cost of log(m) updates to the table for each journey event. This is not an
insignificant cost, but it is highly predictable.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `journey_id (integer not null references journeys(id) on delete cascade)`: the
    journey this entry is for
-   `category (text not null)`: the category this is for. see the categories section
    below.
-   `category_value (integer null)`: the value for the category, if the category has
    a value. see the categories section below.
-   `idx (integer not null)`: the one-based index of the bin in the fenwick tree
    algorithm. Journey times are converted to indices by taking the floor of the
    journey time divided by the bin size, where the bin size is selected as if by
    the following:

    ```txt
    set the number of bins to 2
    while the time width of each bin is more than 1 second:
        double the number of bins
    reduce the number of bins by 1
    ```

    The bin size is normally [cached](../../../websocket/docs/diskcache/keys.md)

-   `val (integer not null)` the value of the bin in the fenwick tree algorithm.

## Categories

-   `users`: the number of join events minus the number of leave events. no category value.
-   `likes`: the number of likes for the journey. no category value.
-   `numeric_active`: the number of active numeric prompt responses with the given rating.
    the category value is the rating.
-   `press_active`: the number of press prompt start events minus the number of press
    prompt end events. no category value
-   `press`: the number of press prompt start events. no category value.
-   `color_active`: the number of active color prompt responses with the given index. the
    category value is the index.
-   `word_active`: the number of active word prompt responses with the given index. the
    category value is the index.

## Prefix Sum Algorithm

https://static.aminer.org/pdf/PDF/001/073/976/a_new_data_structure_for_cumulative_frequency_tables.pdf

This section describes how to retrieve the prefix sum at a given index,
which is the total up to and including the end of the time bin represented
by the index.

The following function produces the relevant time bins for a given journey
which is split into `capacity` different bins.

```py
def time_bins_for_read(index: int, capacity: int) -> Generator[int, None, None]:
    one_based_index = index + 1
    while one_based_index > 0:
        yield one_based_index - 1
        one_based_index -= one_based_index & -one_based_index
```

The bit manipulation is simply a way to get the last set bit of the index by a
bitwise AND with the two's complement of the index. e.g., 5 is 101 in binary, so
5 & -5 is 101 & 011, which is 001, or 1 - the first set bit. Similarly, 6 is 110
in binary, so 6 & -6 is 110 & 010, which is 010, or 2 - the first set bit.
Lastly, 92 is 1011100 in binary, so 92 & -92 is 0000000001011100 &
1111111110100100, which is 100, or 4 - the first set bit.

Summing the value of the given bins for the given journey and category
produces the prefix sum. The algorithm produces at most log_2(capacity)
bins.

## Increment Algorithm

The following function produces the relevant time bins to update for an
event already binarized into the given index for a journey with the given
capacity.

```py
def time_bins_for_update(index: int, capacity: int) -> Generator[int, None, None]:
    one_based_index = index + 1
    while one_based_index <= capacity:
        yield one_based_index - 1
        one_based_index += one_based_index & -one_based_index
```

Incrementing the value of the given bins for the given journey and category
by the number of events will update the prefix sum. The algorithm produces
at most log_2(capacity) bins.

## Schema

```sql
CREATE TABLE journey_event_fenwick_trees (
    id INTEGER PRIMARY KEY,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    category_value INTEGER NULL,
    idx INTEGER NOT NULL,
    val INTEGER NOT NULL
);

/* uniqueness, foreign key, search */
CREATE UNIQUE INDEX journey_event_fenwick_trees_journey_id_category_cvalue_idx_idx
    ON journey_event_fenwick_trees (journey_id, category, category_value, idx);

/* uniqueness when category value is null */
CREATE UNIQUE INDEX journey_event_fenwick_trees_journey_id_category_idx_idx
    ON journey_event_fenwick_trees (journey_id, category, idx) WHERE category_value IS NULL;
```
