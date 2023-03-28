# public_interactive_prompts

This table is primarily to assist with data analysis and is not a core part
of how public interactive prompts work. Each row tracks that a particular
interactive prompt was created as a public interactive prompt, as well as
the identifier.

See [start_public](../../interactive_prompts/routes/start_public.py) for
where public interactive prompts are defined live. This contains a record
of both historical and live public interactive prompts.

## Identifiers

The identifiers that we have used or are using:

- `onboarding-prompt-feeling`: The first interactive prompt a user going through
  onboarding sees. A word prompt asking them what their goal is today, with feeling
  answers.

  - v0: `Today, I am here to...` with `['Relax', 'Destress', 'Focus']`

- `onboarding-prompt-feeling-result`: The interactive prompt the user sees after taking
  the introductory one minute class. A word prompt with feeling responses

  - v0: `How did that class make you feel?` with `['Calming', 'Chill', 'I\'m vibing it']`

- `notification-time`: The interactive prompt that the user sees in order to select when
  they want to see reminders. A word prompt with time responses:

  - v0: `When do you want to receive text reminders?` with `['Morning', 'Afternoon', 'Evening']`

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `pip`
- `interactive_prompt_id (integer unique not null references interactive_prompts(id) on delete cascade)`
- `public_identifier (text not null)`: A value from the `identifiers` section above
- `version (integer not null)`: The version of the identifier

## Schema

```sql
CREATE TABLE public_interactive_prompts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    interactive_prompt_id INTEGER UNIQUE NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
    public_identifier TEXT NOT NULL,
    version INTEGER NOT NULL
);

/* Search */
CREATE INDEX public_interactive_prompts_public_identifier_version_idx ON public_interactive_prompts(public_identifier, version);
```
