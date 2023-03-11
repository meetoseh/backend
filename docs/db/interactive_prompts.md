# interactive_prompts

An interactive prompt refers to a question or activity that users can perform,
where they can see other users responses in a time-dilated fashion. In particular,
users are "synced up" so that everyone sees each others interactions as if they
had all joined the prompt at the same time.

This is most notably for use in journey lobbies, but can also be sprinkled
throughout the rest of the app both in order to train users on how these
prompts work and since they are really neat!

Interactive prompts are tied to their responses - generally, a prompt must
be cloned in order to be reused without sharing the old responses.

Interactive prompts have their own authorization technique in order to separate
why a user can interact with an interactive prompts from the implemetnation of
interactive prompts. See `interactive_prompts/auth.py`

## Prompts

This section describes the possible prompts. Prompts are stored as json blobs,
serialized as if from one of the following:

```py
class NumericPrompt:
    """E.g., What's your mood? 1-10
    Max 10 different values
    """
    style: Literal["numeric"]
    text: str
    min: int
    """inclusive"""
    max: int
    """inclusive"""
    step: int

class PressPrompt:
    """E.g., press when you like it"""
    style: Literal["press"]
    text: str

class ColorPrompt:
    """E.g., what color is this song?"""
    style: Literal["color"]
    text: str
    colors: List[str]
    """hex codes"""

class WordPrompt:
    """e.g. what are you feeling?"""
    style: Literal["word"]
    text: str
    options: List[str]
```

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ip`.
- `prompt (text not null)`: describes the activity that users perform
- `duration_seconds (integer not null)`: how long the interactive prompt lasts.
  Due to how interactive prompts are achieved, a time limit must be placed on
  responses to guarrantee bounded memory/cpu costs. This field cannot generally
  be changed losslessly, and changing it without updating the fenwick trees
  and counts will result in extremely undesirable side-effects
- `created_at (real not null)`: When the row was created in seconds since the epoch
- `deleted_at (real null)`: If this prompt should no longer be used, the time it
  was most recently marked deleted, otherwise null.

## Schema

```sql
CREATE TABLE interactive_prompts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    prompt TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    created_at REAL NOT NULL,
    deleted_at REAL NULL
);
```
