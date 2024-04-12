import asyncio
import io
import random
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Union,
    cast,
)
from pydantic import BaseModel, Field
from itgs import Itgs
from personalization.home.copy.lib.context import (
    HomescreenClientVariant,
    HomescreenCopyContext,
)
from users.lib.time_of_day import get_time_of_day
from users.lib.streak import read_user_streak
import hashlib
import base64
import unix_dates
import time
from loguru import logger

from users.lib.timezones import get_user_timezone


class HomescreenHeadline(BaseModel):
    slug: str = Field(
        description="A unique identifier for this headline, stable to minor edits (e.g., typos)"
    )
    headline: str = Field("", description="The large text at the top")
    subheadline: str = Field("", description="The smaller text below the headline")
    composed_slugs: List[str] = Field(
        default_factory=list,
        description="The slugs of the headlines that were composed to make this one",
    )


class HomescreenHeadlineGenerator(Protocol):
    """Describes something which can incorporate homescreen context to generate
    a headline, unless the context doesn't make sense for this generator, in which
    case it returns None.
    """

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        """A faster, non-concurrent check to see if this generator will return a value.

        Returns:
            True if its possible the generator will return a value, False if it will
            definitely not return a value.
        """
        ...

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]: ...


class SimpleHomescreenGenerator:
    """The simplest headline generator which always returns the same value"""

    def __init__(
        self,
        slug: str,
        *,
        headline: Union[str, Callable[[HomescreenCopyContext], str]] = "",
        subheadline: Union[str, Callable[[HomescreenCopyContext], str]] = "",
    ) -> None:
        self.headline = headline
        self.subheadline = subheadline
        self.slug = slug

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        return True

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if isinstance(self.headline, str):
            headline = self.headline
        else:
            headline = self.headline(ctx)

        if isinstance(self.subheadline, str):
            subheadline = self.subheadline
        else:
            subheadline = self.subheadline(ctx)

        return HomescreenHeadline(
            headline=headline,
            subheadline=subheadline,
            slug=self.slug,
            composed_slugs=[],
        )


class RandomHomescreenGenerator:
    """A headline generator which selects uniformly at random without replacement from
    the sub-generators which have valid options, refreshing the list when they are exhausted.

    If `slugs_are_stable` is specified, the subgenerators must always return a
    value and that value must have the same slug, and the query can be optimized
    significantly (by not having to regenerate the list of slugs each time)

    If using split generators, this assumes you random the headline independently,
    then the subheadline independently, and then combine them after (so that this
    never needs to worry about subgenerators returning composed slugs)
    """

    def __init__(
        self, generators: List[HomescreenHeadlineGenerator], *, slugs_are_stable: bool
    ) -> None:
        assert generators, "Must have at least one generator"

        self.generators = generators
        self.slugs_are_stable = slugs_are_stable

        self._generators_by_slug: Optional[Dict[str, HomescreenHeadlineGenerator]] = (
            None
        )
        self._query: Optional[str] = None
        self._slugs: Optional[List[str]] = None

    def _get_query(self, slugs: Iterable[str]) -> str:
        query = io.StringIO()
        query.write("WITH batch(slug) AS (VALUES (?)")
        for i, _ in enumerate(slugs):
            if i > 0:
                query.write(", (?)")
        query.write(
            """),
seen_counts(slug, cnt) AS (
SELECT
    batch.slug,
    (
        SELECT COUNT(*) FROM user_home_screen_copy
        WHERE
            user_home_screen_copy.user_id = (SELECT users.id FROM users WHERE users.sub = ?)
            AND (
                user_home_screen_copy.slug = batch.slug
                OR (
                    json_array_length(user_home_screen_copy.composed_slugs) > 0
                    AND json_extract(user_home_screen_copy.composed_slugs, '$[0]') = batch.slug
                )
                OR (
                    json_array_length(user_home_screen_copy.composed_slugs) > 1
                    AND json_extract(user_home_screen_copy.composed_slugs, '$[1]') = batch.slug
                )
            ) 
    )
FROM batch
)
SELECT
    seen_counts.slug 
FROM seen_counts 
WHERE
    seen_counts.cnt = (SELECT MIN(sc.cnt) FROM seen_counts AS sc)
            """
        )
        return query.getvalue()

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if self.slugs_are_stable:
            return True
        return any(g.precheck(ctx) for g in self.generators)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if self.slugs_are_stable:
            if (
                self._query is None
                or self._slugs is None
                or self._generators_by_slug is None
            ):
                generated = await asyncio.gather(
                    *[g(itgs, ctx) for g in self.generators]
                )

                assert all(
                    g is not None for g in generated
                ), "if slugs_are_stable, all generators must return a value"
                generated = cast(List[HomescreenHeadline], generated)

                assert all(
                    not g.composed_slugs for g in generated
                ), "RandomHomescreenGenerator does not support composed children"
                slugs = [gen.slug for gen in generated]

                self._query = self._get_query(slugs)
                self._slugs = slugs
                self._generators_by_slug = dict(
                    (gen.slug, generator)
                    for (gen, generator) in zip(generated, self.generators)
                )

                query = self._query
                generators_by_slug = self._generators_by_slug
            else:
                generated = None
                query = self._query
                slugs = self._slugs
                generators_by_slug = self._generators_by_slug
        else:
            generated = await asyncio.gather(*[g(itgs, ctx) for g in self.generators])
            slugs = [
                cast(HomescreenHeadline, gen).slug
                for gen in generated
                if gen is not None
            ]
            if not slugs:
                return None

            assert all(
                gen is None or not gen.composed_slugs for gen in generated
            ), "RandomHomescreenGenerator does not support composed children"

            query = self._get_query(slugs)
            generators_by_slug = dict(
                (cast(HomescreenHeadline, gen).slug, generator)
                for (gen, generator) in zip(generated, self.generators)
                if gen is not None
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        if len(slugs) > 40:
            # try a random one to see if it hasn't been taken before
            optimistic_slug = random.choice(slugs)
            optimistic_response = await cursor.execute(
                "SELECT 1 FROM user_home_screen_copy, users "
                "WHERE"
                " user_home_screen_copy.slug = ?"
                " AND user_home_screen_copy.user_id = users.id"
                " AND users.sub = ?",
                [optimistic_slug, ctx.user_sub],
            )
            if not optimistic_response.results:
                return await generators_by_slug[optimistic_slug](itgs, ctx)

        response = await cursor.execute(query, slugs + [ctx.user_sub])
        assert response.results, response

        number_of_options = len(response.results)
        choice_index = random.randint(0, number_of_options - 1)
        chosen_slug = response.results[choice_index][0]

        if generated is not None and len(generated) < 6:
            return next(
                gen for gen in generated if gen is not None and gen.slug == chosen_slug
            )

        generator = generators_by_slug[chosen_slug]
        return await generator(itgs, ctx)


class SplitHeadlineSubheadlineGenerator:
    """Describes a generator which fetches the headline from one generator and the
    subheadline from the other
    """

    def __init__(
        self,
        slug: str,
        headline_generator: HomescreenHeadlineGenerator,
        subheadline_generator: HomescreenHeadlineGenerator,
    ) -> None:
        self.slug = slug
        self.headline_generator = headline_generator
        self.subheadline_generator = subheadline_generator

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        return self.headline_generator.precheck(
            ctx
        ) and self.subheadline_generator.precheck(ctx)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None

        headline, subheadline = await asyncio.gather(
            self.headline_generator(itgs, ctx),
            self.subheadline_generator(itgs, ctx),
        )
        if headline is None or subheadline is None:
            return None

        return HomescreenHeadline(
            slug=self.slug,
            headline=headline.headline,
            subheadline=subheadline.subheadline,
            composed_slugs=[headline.slug, subheadline.slug],
        )


class TimeOfDayGenerator:
    """A generator that delegates to the specified sub-generator based on the time
    of day the user will see the homescreen.
    """

    def __init__(
        self,
        *,
        morning: HomescreenHeadlineGenerator,
        afternoon: HomescreenHeadlineGenerator,
        evening: HomescreenHeadlineGenerator,
    ) -> None:
        self.morning = morning
        self.afternoon = afternoon
        self.evening = evening

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        tod = get_time_of_day(ctx.show_at, ctx.show_tz)
        if tod == "morning":
            return self.morning.precheck(ctx)
        elif tod == "afternoon":
            return self.afternoon.precheck(ctx)
        elif tod == "evening":
            return self.evening.precheck(ctx)
        return False

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        tod = get_time_of_day(ctx.show_at, ctx.show_tz)
        if tod == "morning":
            return await self.morning(itgs, ctx)
        elif tod == "afternoon":
            return await self.afternoon(itgs, ctx)
        elif tod == "evening":
            return await self.evening(itgs, ctx)
        raise ValueError(f"Unexpected time of day: {tod}")


def _name(ctx: HomescreenCopyContext) -> str:
    if ctx.given_name is None:
        return ""
    return f", {ctx.given_name}"


_fixed = SimpleHomescreenGenerator
_session_start_headline_only = RandomHomescreenGenerator(
    [
        TimeOfDayGenerator(
            morning=_fixed(
                "ssho_time_of_day_greeting",
                headline=lambda ctx: f"Good morning{_name(ctx)}! 👋",
            ),
            afternoon=_fixed(
                "ssho_time_of_day_greeting",
                headline=lambda ctx: f"Good afternoon{_name(ctx)}! 👋",
            ),
            evening=_fixed(
                "ssho_time_of_day_greeting",
                headline=lambda ctx: f"Good evening{_name(ctx)}! 👋",
            ),
        ),
        _fixed(
            "ssho_welcome_back", headline=lambda ctx: f"Welcome back{_name(ctx)}! 👋"
        ),
        _fixed(
            "ssho_find_calm",
            headline=lambda ctx: f"Let’s find your calm{_name(ctx)}. 🌊",
        ),
        _fixed(
            "ssho_moment_of_peace",
            headline=lambda ctx: f"Your moment of peace awaits{_name(ctx)}. ✨",
        ),
        _fixed(
            "ssho_enjoy_today",
            headline=lambda ctx: f"Enjoy today’s journey{_name(ctx)}. 🌟",
        ),
        _fixed("ssho_breathe", headline=lambda ctx: f"Time to breathe{_name(ctx)}. 💨"),
    ],
    slugs_are_stable=True,
)
"""Filler session start headlines"""

_session_end_headline_only = RandomHomescreenGenerator(
    [
        _fixed(
            "seho_beautiful_practice",
            headline=lambda ctx: f"Beautiful practice{_name(ctx)} 🙏",
        ),
        _fixed(
            "seho_nice_class",
            headline=lambda ctx: f"Nice class{_name(ctx)}! 🌟",
        ),
        _fixed(
            "seho_peace_be_upon_you",
            headline=lambda ctx: f"Peace be upon you{_name(ctx)}. 🍃",
        ),
        _fixed(
            "seho_glowing",
            headline=lambda ctx: f"You’re glowing{_name(ctx)}! 🌈",
        ),
    ],
    slugs_are_stable=True,
)
"""Filler session head headlines"""


def _quote(text: str, author: str) -> HomescreenHeadlineGenerator:
    quote = "“" + text + "” —" + author
    quote_md5 = base64.urlsafe_b64encode(hashlib.md5(quote.encode()).digest()).decode()
    author_simple = author.replace(" ", "_").lower()
    return _fixed(slug=f"q-{author_simple}-{quote_md5}", subheadline=quote)


_quote_subheadlines_only = RandomHomescreenGenerator(
    [
        _quote(
            "Mindfulness isn’t difficult, we just need to remember to do it.",
            "Sharon Salzberg",
        ),
        _quote(
            "The best way to capture moments is to pay attention.", "Jon Kabat-Zinn"
        ),
        _quote(
            "Feelings come and go like clouds in a windy sky. Conscious breathing is my anchor.",
            "Thich Nhat Hanh",
        ),
        _quote(
            "In today’s rush, we all think too much, seek too much, want too much, and forget about the joy of just being.",
            "Eckhart Tolle",
        ),
        _quote(
            "The goal of meditation isn’t to control your thoughts, it’s to stop letting them control you.",
            "Anonymous",
        ),
        _quote(
            "Almost everything will work again if you unplug it for a few minutes, including you.",
            "Anne Lamott",
        ),
        _quote(
            "The soul always knows what to do to heal itself. The challenge is to silence the mind.",
            "Caroline Myss",
        ),
        _quote(
            "Mindfulness means being awake. It means knowing what you are doing.",
            "Jon Kabat-Zinn",
        ),
        _quote(
            "The little things? The little moments? They aren’t little.",
            "Jon Kabat-Zinn",
        ),
        _quote("Wherever you are, be there totally.", "Eckhart Tolle"),
        _quote(
            "Meditation and concentration are the way to a life of serenity.",
            "Baba Ram Dass",
        ),
        _quote("Peace comes from within. Do not seek it without.", "Buddha"),
        _quote(
            "Mindfulness is a way of befriending ourselves and our experience.",
            "Jon Kabat-Zinn",
        ),
        _quote(
            "You have a treasure within you that is infinitely greater than anything the world can offer.",
            "Eckhart Tolle",
        ),
        _quote("The art of peace is medicine for a sick world.", "Morihei Ueshiba"),
        _quote(
            "Respond; don’t react. Listen; don’t talk. Think; don’t assume.",
            "Raji Lukkoor",
        ),
        _quote(
            "The present moment is filled with joy and happiness. If you are attentive, you will see it.",
            "Thich Nhat Hanh",
        ),
        _quote("Serenity comes when you trade expectations for acceptance.", "Unknown"),
        _quote(
            "Meditation is not a way of making your mind quiet. It’s a way of entering into the quiet that is already there.",
            "Deepak Chopra",
        ),
        _quote(
            "The present moment is the only time over which we have dominion.",
            "Thich Nhat Hanh",
        ),
        _quote(
            "The simplification of life is one of the steps to inner peace.",
            "Peace Pilgrim",
        ),
        _quote(
            "The thing about meditation is: You become more and more you.",
            "David Lynch",
        ),
        _quote(
            "When meditation is mastered, the mind is unwavering like the flame of a candle in a windless place.",
            "Bhagavad Gita",
        ),
        _quote(
            "Meditation is a way for nourishing and blossoming the divinity within you.",
            "Amit Ray",
        ),
        _quote(
            "Meditation is the tongue of the soul and the language of our spirit.",
            "Jeremy Taylor",
        ),
        _quote(
            "The quieter you become, the more you can hear.",
            "Ram Dass",
        ),
        _quote(
            "Happiness is not something ready-made. It comes from your own actions",
            "Dalai Lama",
        ),
        _quote(
            "You must live in the present, launch yourself on every wave, find your eternity in each moment.",
            "Henry David Thoreau",
        ),
        _quote(
            "True happiness is born of letting go of what is unnecessary.",
            "Sharon Salzberg",
        ),
        _quote(
            "Self-observation is the first step of inner unfolding.", "Amit Goswami"
        ),
        _quote("The quieter you become, the more you can hear.", "Ram Dass"),
        _quote(
            "Don’t believe everything you think. Thoughts are just that – thoughts.",
            "Allan Lokos",
        ),
        _quote("The art of knowing is knowing what to ignore.", "Rumi"),
        _quote("Being present is being connected to All Things.", "S. Kelley Harrell"),
        _quote("Awareness is the greatest agent for change.", "Eckhart Tolle"),
        _quote(
            "You must live in the present, launch yourself on every wave, find your eternity in each moment.",
            "Henry David Thoreau",
        ),
        _quote(
            "Mindfulness is not a mechanical process. It is developing a very gentle, kind, and creative awareness to the present moment.",
            "Amit Ray",
        ),
        _quote(
            "The mind is like water. When it’s turbulent, it’s difficult to see. When it’s calm, everything becomes clear.",
            "Prasad Mahes",
        ),
        _quote("You are the sky. Everything else is just the weather.", "Pema Chödrön"),
        _quote(
            "The things that matter most in our lives are not fantastic or grand. They are moments when we touch one another.",
            "Jack Kornfield",
        ),
        _quote(
            "Do not dwell in the past, do not dream of the future, concentrate the mind on the present moment.",
            "Buddha",
        ),
        _quote(
            "In today’s rush, we all think too much, seek too much, want too much and forget about the joy of just being.",
            "Eckhart Tolle",
        ),
        _quote(
            "Let go of your mind and then be mindful. Close your ears and listen!",
            "Rumi",
        ),
        _quote(
            "Be kind whenever possible. It is always possible.",
            "Dalai Lama",
        ),
        _quote(
            "Silence is not an absence but a presence.",
            "Anne D. LeClaire",
        ),
        _quote(
            "The best way to capture moments is to pay attention. This is how we cultivate mindfulness.",
            "Jon Kabat-Zinn",
        ),
        _quote(
            "The real meditation is how you live your life.",
            "Jon Kabat-Zinn",
        ),
        _quote(
            "Wherever you are, be there totally.",
            "Eckhart Tolle",
        ),
        _quote(
            "Meditation practice isn’t about trying to throw ourselves away and become something better.",
            "Pema Chödrön",
        ),
        _quote(
            "Mindfulness is a way of befriending ourselves and our experience.",
            "Jon Kabat-Zinn",
        ),
        _quote(
            "The art of peaceful living comes down to living compassionately & wisely.",
            "Allan Lokos",
        ),
    ],
    slugs_are_stable=True,
)


def _tip(text: str) -> HomescreenHeadlineGenerator:
    return _fixed(
        slug=f"tip-{base64.urlsafe_b64encode(hashlib.md5(text.encode()).digest()).decode()}",
        subheadline=text,
    )


_tip_subheadlines_only = RandomHomescreenGenerator(
    [
        _tip("Embrace each moment fully, allowing presence to be your guide."),
        _tip("Acknowledge your thoughts gently, then focus back on your breath."),
        _tip("Start with gratitude to center your mind before each session."),
        _tip("Release all expectations and immerse fully in the experience."),
        _tip("Pay attention to your body's sensations as you settle into practice."),
        _tip("Ensure your practice space is comfortable, safe, and inviting."),
        _tip("Approach each session with openness, ready for any experience."),
        _tip("Understand there's no 'right' feeling; practice is personal and unique."),
        _tip("After each class, take time to appreciate your dedication and effort."),
        _tip("When your mind wanders, gently guide it back with focused breathing."),
        _tip("Choose a quiet space to practice, minimizing distractions around you."),
        _tip("Maintaining presence in each moment enhances your mindfulness journey."),
        _tip(
            "Regularly acknowledging thoughts helps in returning focus to your breath."
        ),
        _tip("A small act of gratitude can deeply center you before starting."),
        _tip(
            "Letting go of expectations allows you to fully experience your practice."
        ),
        _tip("Noticing bodily sensations helps ground you in the present moment."),
        _tip("Creating a comforting space enhances your meditation experience."),
        _tip("Being open to all experiences enriches your practice and growth."),
        _tip("Remembering there’s no correct way to feel validates your experience."),
        _tip("Valuing your effort reinforces your commitment to growth."),
        _tip("Finding a serene space supports a deeper, distraction-free meditation."),
        _tip("Adjusting your posture aids in maintaining alertness and comfort."),
        _tip("Softly closing your eyes can help turn your focus inward."),
        _tip("Taking deep breaths before starting settles your mind and body."),
        _tip("A gentle smile can cultivate an atmosphere of warmth and ease."),
        _tip("Scanning your body to release tension prepares you for deeper practice."),
        _tip("Visualizing a peaceful place can enhance your meditation experience."),
        _tip("Using a soft gaze helps if you prefer meditating with open eyes."),
        _tip(
            "Embracing silence deepens your meditation, enriching your practice’s focus."
        ),
        _tip(
            "Grounding yourself before class with deep breaths brings immediate calm."
        ),
        _tip(
            "You can share classes with friends to deepen your practice and connection."
        ),
        _tip(
            "You can tap your goal at any time to set a new intention for your practice."
        ),
        _tip("You can update your reminders by tapping Account in the bottom right."),
        _tip("Series are great for deepening your practice and exploring new themes."),
        _tip("Contact us via hi@oseh.com for any questions or feedback."),
        _tip("Know a great quote? Share it with us on instagram @meetoseh"),
    ],
    slugs_are_stable=True,
)


class GoalOneSessionAwaySubheadlineOnlyGenerator:
    def __init__(self) -> None:
        self.subgenerator = RandomHomescreenGenerator(
            [
                _fixed(
                    "gosa_almost_there",
                    subheadline="Almost there! Practice now to make your goal 🌟",
                ),
                _fixed(
                    "gosa_nearly_at_goal",
                    subheadline=lambda ctx: f"Nearly at your goal! 🚀 Meditate now to complete your goal of {ctx.streak.goal_days_per_week} day{'s' if ctx.streak.goal_days_per_week != 1 else ''} this week.",
                ),
                _fixed(
                    "gosa_nearly_there",
                    subheadline=lambda ctx: f"Nearly there! Your {ctx.streak.goal_days_per_week}-day goal is within reach. Embrace your progress.",
                ),
            ],
            slugs_are_stable=True,
        )

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_start" or ctx.taken_class_today:
            return False

        if ctx.streak.goal_days_per_week is None:
            return False

        if len(ctx.streak.days_of_week) + 1 != ctx.streak.goal_days_per_week:
            return False

        return True

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None

        return await self.subgenerator(itgs, ctx)


class GoalTwoSessionsAwaySubheadlineOnlyGenerator:
    def __init__(self) -> None:
        self.subgenerator = RandomHomescreenGenerator(
            [
                _fixed(
                    "gtsa_just",
                    subheadline="Just two more sessions for a perfect week! You’re creating wonderful habits",
                ),
                _fixed(
                    "gtsa_only",
                    subheadline=lambda ctx: f"Only two more sessions to your {ctx.streak.goal_days_per_week}-day goal. Your commitment is inspiring. Keep it up!",
                ),
                _fixed(
                    "gtsa_nearly_there",
                    subheadline=lambda ctx: f"Nearly there! Your {ctx.streak.goal_days_per_week}-day goal is within reach. Keep going!",
                ),
            ],
            slugs_are_stable=True,
        )

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_start" or ctx.taken_class_today:
            return False

        if ctx.streak.goal_days_per_week is None:
            return False

        if len(ctx.streak.days_of_week) + 2 != ctx.streak.goal_days_per_week:
            return False

        unix_date_today = unix_dates.unix_timestamp_to_unix_date(
            ctx.show_at, tz=ctx.show_tz
        )
        unix_weekday_today = unix_dates.unix_date_to_date(unix_date_today).weekday()
        if unix_weekday_today == 6:
            return False

        return True

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None
        return await self.subgenerator(itgs, ctx)


def _post_class(text: str) -> HomescreenHeadlineGenerator:
    return _fixed(
        slug=f"post-class-{base64.urlsafe_b64encode(hashlib.md5(text.encode()).digest()).decode()}",
        subheadline=text,
    )


_session_end_subheadlines_only = RandomHomescreenGenerator(
    [
        _post_class("Thank you for sharing your practice with us today."),
        _post_class("Thank you for committing to your growth and tranquility today."),
        _post_class("Thank you for joining us today."),
        _post_class("Every moment of mindfulness adds to your journey. Keep going."),
        _post_class("Great work today! Your dedication is inspiring."),
        _post_class("Remember, each practice enriches your path to calm."),
        _post_class("Let the peace you cultivated stay with you."),
        _post_class("Your presence today was powerful. Keep embracing this path."),
        _post_class("Nice practice today. Let’s carry this calm into today."),
        _post_class("Thank you for committing to your growth and tranquility today."),
    ],
    slugs_are_stable=True,
)


class ClassMilestoneGenerator:
    def __init__(self, milestone: int, headline: str, subheadline: str) -> None:
        self.milestone = milestone
        self.headline = headline
        self.subheadline = subheadline

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        if ctx.streak.journeys != self.milestone:
            return False

        return True

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None

        return HomescreenHeadline(
            headline=self.headline,
            subheadline=self.subheadline,
            slug=f"class-milestone-{self.milestone}",
        )


class ClassMilestonesGenerator:
    """Faster than just iterating through all milestones"""

    def __init__(self, milestones: List[ClassMilestoneGenerator]) -> None:
        self.milestones = milestones
        self._milestones_by_milestone = dict((m.milestone, m) for m in milestones)

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        return ctx.streak.journeys in self._milestones_by_milestone

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if ctx.client_variant != "session_end":
            return None

        milestone = self._milestones_by_milestone.get(ctx.streak.journeys)
        if milestone is None:
            return None

        return await milestone(itgs, ctx)


_class_milestones = ClassMilestonesGenerator(
    [
        ClassMilestoneGenerator(
            1,
            "Your First Class 🌟",
            "Here’s to starting a journey of calm and clear mindfulness. ",
        ),
        ClassMilestoneGenerator(
            10,
            "Celebrating 10 Classes 🌟",
            "Ten classes in, and you’re on a beautiful path to inner stillness. Keep embracing the journey.",
        ),
        ClassMilestoneGenerator(
            25,
            "Celebrating 25 Classes!",
            "Twenty-five classes of mindfulness! 🌈 You’re building a wonderful habit of peace and positivity.",
        ),
        ClassMilestoneGenerator(
            50,
            "Recognizing 50 Classes",
            "Fifty classes down! 🌞 Your dedication is so inspiring. We love seeing your personal growth.",
        ),
        ClassMilestoneGenerator(
            75,
            "Honoring 75 Classes",
            "Seventy-five classes! You’re deepening your mindfulness journey beautifully. Your inner calm is shining through.",
        ),
        ClassMilestoneGenerator(
            100,
            "Celebrating 100 Classes",
            "A hundred classes! 🌿 That’s true dedication to your self. You are doing amazing!",
        ),
        ClassMilestoneGenerator(
            150,
            "Celebrating 150 Classes",
            "What a milestone! 🌠 Each class a step towards deeper harmony. Fantastic work!",
        ),
        ClassMilestoneGenerator(
            200,
            "Recognizing 200 Classes",
            "Two hundred classes! Your inner light shines brightly! 🌞 ",
        ),
        ClassMilestoneGenerator(
            250,
            "Celebrating 250 Classes",
            "250 classes! 🌊 You’re deepening your mindfulness every day, enriching your life with calm centeredness.",
        ),
        ClassMilestoneGenerator(
            300,
            "Honoring 300 Classes",
            "Three hundred classes! 🌊 Your commitment to mindfulness is impressive. Each session brings more understanding and tranquility.",
        ),
    ]
)


class AnniversaryGenerator:
    def __init__(
        self,
        days: int,
        headline: str,
        subheadline: Union[str, Callable[[HomescreenCopyContext], str]],
    ) -> None:
        self.days = days
        self.headline = headline
        self.subheadline = subheadline

    @property
    def slug(self) -> str:
        return f"anniversary-P{self.days}D"

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.user_created_at, tz=ctx.show_tz
        )
        now_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.show_at, tz=ctx.show_tz
        )

        days_since_created = now_unix_date - created_at_unix_date

        if days_since_created < self.days:
            return False

        if days_since_created > self.days + 2:
            return False

        return True

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "SELECT 1 FROM user_home_screen_copy, users "
            "WHERE"
            " user_home_screen_copy.slug = ?"
            " AND user_home_screen_copy.user_id = users.id"
            " AND users.sub = ?",
            [self.slug, ctx.user_sub],
        )
        if response.results:
            return None

        if isinstance(self.subheadline, str):
            subheadline = self.subheadline
        else:
            subheadline = self.subheadline(ctx)

        return HomescreenHeadline(
            headline=self.headline,
            subheadline=subheadline,
            slug=self.slug,
        )


class AnniversariesGenerator:
    """Faster than just iterating through the anniversaries"""

    def __init__(self, generators: List[AnniversaryGenerator]) -> None:
        self.generators = generators
        self._generators_by_days: Dict[int, AnniversaryGenerator] = dict()

        for generator in sorted(generators, key=lambda g: g.days):
            for days in range(generator.days, generator.days + 7):
                self._generators_by_days[days] = generator

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.user_created_at, tz=ctx.show_tz
        )
        now_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.show_at, tz=ctx.show_tz
        )

        days_since_created = now_unix_date - created_at_unix_date
        return days_since_created in self._generators_by_days

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if ctx.client_variant != "session_end":
            return None

        created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.user_created_at, tz=ctx.show_tz
        )
        now_unix_date = unix_dates.unix_timestamp_to_unix_date(
            ctx.show_at, tz=ctx.show_tz
        )

        days_since_created = now_unix_date - created_at_unix_date
        generator = self._generators_by_days.get(days_since_created)
        if generator is None:
            return None

        return await generator(itgs, ctx)


_anniversaries = AnniversariesGenerator(
    [
        AnniversaryGenerator(
            7,
            "Cheers to your first week! 🎉",
            lambda ctx: f"Congratulations on your first week with us{_name(ctx)}! 🌟 Keep embracing the calm.",
        ),
        AnniversaryGenerator(
            30,
            "It’s your one month anniversary!",
            lambda ctx: f"One month of mindfulness{_name(ctx)}. 🎉 Your journey is inspiring. Keep growing. 🌈",
        ),
        AnniversaryGenerator(
            91,
            "Celebrating 3 months of mindfulness!",
            lambda ctx: f"Three months{_name(ctx)}. 🌟 Your presence is evolving beautifully. Well done.",
        ),
        AnniversaryGenerator(
            182,
            "It’s your 6 month anniversary!",
            lambda ctx: f"Six months of mindfulness{_name(ctx)}. Your path is inspiring. Keep shining. 🌈",
        ),
        AnniversaryGenerator(
            273,
            "Your nine month Anniversary!",
            lambda ctx: f"Nine months in{_name(ctx)}. 🌟  Each moment has deepened your peace. Amazing progress.",
        ),
        AnniversaryGenerator(
            365,
            "One Year with Oseh",
            lambda ctx: f"Happy 1-Year Anniversary{_name(ctx)}! 🌿 A whole year of growth. Each moment has deepened your peace. ",
        ),
        AnniversaryGenerator(
            365 + 182,
            "18 Months with Oseh",
            lambda ctx: f"Eighteen months{_name(ctx)}, and your mindfulness journey continues to flourish. Beautiful practice. 🌟",
        ),
        AnniversaryGenerator(
            365 * 2,
            "Your two year Anniversary!",
            lambda ctx: f"Two years of mindfulness{_name(ctx)}. Your path is inspiring. Keep shining. 🌈",
        ),
        AnniversaryGenerator(
            365 * 3,
            "Your three year Anniversary!",
            lambda ctx: f"Three years of mindfulness{_name(ctx)}. Your path is inspiring. Keep shining. 🌈",
        ),
        AnniversaryGenerator(
            365 * 4,
            "Your four year Anniversary!",
            lambda ctx: f"Four years of mindfulness{_name(ctx)}. Your path is inspiring. Keep shining. 🌈",
        ),
    ]
)


def _days(ctx: HomescreenCopyContext) -> str:
    assert ctx.streak.goal_days_per_week is not None
    return f"{ctx.streak.goal_days_per_week} day{'s' if ctx.streak.goal_days_per_week != 1 else ''}"


class GoalCompleteGenerator:
    def __init__(self) -> None:
        self.headline_only = RandomHomescreenGenerator(
            [
                _fixed(
                    "gc_h_practiced_this_week",
                    headline=lambda ctx: f"{_days(ctx)} practiced this week! 🙌",
                ),
                _fixed("gc_h_accomplished", headline="Weekly goal accomplished! 👏"),
                _fixed(
                    "gc_h_well_done", headline=lambda ctx: f"Well done{_name(ctx)}! 👏"
                ),
                _fixed(
                    "gd_h_weekly_goal_complete", headline=f"Weekly Goal Completed! 🙌"
                ),
                _fixed(
                    "gd_h_nice_week", headline=lambda ctx: f"Nice week{_name(ctx)}! 👏"
                ),
            ],
            slugs_are_stable=True,
        )
        self.subheadline_only = RandomHomescreenGenerator(
            [
                _fixed(
                    "gc_sh_completed",
                    subheadline=lambda ctx: f"You’ve just completed your goal of practicing for {_days(ctx)}. Excellent job.",
                ),
                _fixed(
                    "gc_sh_silence",
                    subheadline=lambda ctx: f"{_days(ctx)} of silence this week. Your journey deepens.",
                ),
                _fixed(
                    "gc_sh_great_work",
                    subheadline=lambda ctx: f"Great work practicing {_days(ctx)} this week.",
                ),
                _fixed(
                    "gc_sh_path_to_now",
                    subheadline=lambda ctx: f"Each day, a path to now. {_days(ctx)} of presence.",
                ),
            ],
            slugs_are_stable=True,
        )
        self.subgenerator = SplitHeadlineSubheadlineGenerator(
            "goal-complete",
            self.headline_only,
            self.subheadline_only,
        )

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        if ctx.streak.goal_days_per_week is None:
            return False

        if len(ctx.streak.days_of_week) != ctx.streak.goal_days_per_week:
            return False

        return self.subgenerator.precheck(ctx)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None

        return await self.subgenerator(itgs, ctx)


class StreaksGenerator:
    """Returns the given generator only on relevant streak days"""

    def __init__(self, generator: HomescreenHeadlineGenerator) -> None:
        self.generator = generator

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        if ctx.client_variant != "session_end":
            return False

        return (
            ctx.streak.streak in (3, 7, 14)
            or (ctx.streak.streak > 0 and ctx.streak.streak % 5 == 0)
        ) and self.generator.precheck(ctx)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if not self.precheck(ctx):
            return None
        return await self.generator(itgs, ctx)


class IfBestAllTimeStreakGenerator:
    """Returns the given generator only if the users current streak is their best all-time streak"""

    def __init__(self, generator: HomescreenHeadlineGenerator) -> None:
        self.generator = generator

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        return (
            ctx.streak.streak > ctx.streak.prev_best_all_time_streak
            and self.generator.precheck(ctx)
        )

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        if ctx.streak.streak <= ctx.streak.prev_best_all_time_streak:
            return None

        return await self.generator(itgs, ctx)


_streaks = StreaksGenerator(
    SplitHeadlineSubheadlineGenerator(
        "streak",
        RandomHomescreenGenerator(
            [
                _fixed(
                    "streak_h_celebrating",
                    headline=lambda ctx: f"Celebrating your {ctx.streak.streak}-day streak!",
                ),
                _fixed(
                    "streak_h_honoring",
                    headline=lambda ctx: f"Honoring your new {ctx.streak.streak}-day streak",
                ),
                _fixed(
                    "streak_h_elevating",
                    headline=lambda ctx: f"Elevating Peace: {ctx.streak.streak} Days in a Row! 🕊️",
                ),
                IfBestAllTimeStreakGenerator(
                    RandomHomescreenGenerator(
                        [
                            _fixed("streak_h_new", headline="New all-time streak!"),
                            _fixed(
                                "streak_h_new_peak",
                                headline=lambda ctx: f"A New Peak: {ctx.streak.streak}-Day Streak! 🌄",
                            ),
                        ],
                        slugs_are_stable=True,
                    )
                ),
            ],
            slugs_are_stable=False,
        ),
        RandomHomescreenGenerator(
            [
                _fixed(
                    "streak_sh_each_day_growth",
                    subheadline="Each day adds to your journey of growth.",
                ),
                _fixed(
                    "streak_sh_daily_practice",
                    subheadline="Your daily practice is shaping a more mindful you.",
                ),
                _fixed(
                    "streak_sh_thank_you",
                    subheadline="Thank you for practicing with us!  Your dedication is admirable.",
                ),
                _fixed(
                    "streak_sh_with_every_day",
                    subheadline="With every day, you're deepening your relationship with yourself.",
                ),
                _fixed(
                    "streak_sh_with_every_practice",
                    subheadline="With every practice, you know yourself better.",
                ),
                _fixed(
                    "streak_sh_nurturing",
                    subheadline="Your journey is nurturing a more compassionate self.",
                ),
                _fixed(
                    "streak_sh_cultivating",
                    subheadline="Your practice is cultivating a deeper sense of inner peace.",
                ),
                _fixed(
                    "streak_sh_resilience",
                    subheadline="Each mindful moment fosters greater emotional resilience.",
                ),
                _fixed(
                    "streak_sh_grounded",
                    subheadline="The time you give to yourself is shaping a more grounded you.",
                ),
                _fixed(
                    "streak_sh_clarity",
                    subheadline="Regular practice brings clarity, easing the mind's chatter.",
                ),
                _fixed(
                    "streak_sh_stillness",
                    subheadline="With each day, you’re finding strength in stillness.",
                ),
                _fixed(
                    "streak_sh_balanced",
                    subheadline="Your practice is guiding you to a balanced state of being",
                ),
                _fixed(
                    "streak_sh_mindful",
                    subheadline="Your dedication is revealing a more mindful path.",
                ),
                _fixed(
                    "streak_sh_resonant_calm",
                    subheadline="Your practice is a journey to a deeper, more resonant calm.",
                ),
                _fixed(
                    "streak_sh_self_acceptance",
                    subheadline="Meditation illuminates the path to self-acceptance and contentment.",
                ),
                _fixed(
                    "streak_sh_insights",
                    subheadline="Your commitment to stillness brings profound personal insights.",
                ),
                _fixed(
                    "streak_sh_centered",
                    subheadline="Finding peace in meditation, you’re more centered every day.",
                ),
                _fixed(
                    "streak_sh_enriching",
                    subheadline="Gratitude grows with each session, enriching your life.",
                ),
                _fixed(
                    "streak_sh_compassion",
                    subheadline="Your practice fosters a serene mind and a compassionate heart.",
                ),
            ],
            slugs_are_stable=True,
        ),
    )
)


class SimpleWeightedRandomGenerator:
    """Selects from the sub-generators at random according to the weights, or, if the
    weights aren't specified, uniformly at random. This does not inject itself as the
    slug of the returned headline, and thus can't be used for deduplication
    """

    def __init__(
        self,
        generators: List[HomescreenHeadlineGenerator],
        weights: Optional[List[int]] = None,
    ) -> None:
        self.generators = generators
        self.weights = weights

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        return any(generator.precheck(ctx) for generator in self.generators)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        # This is optimized for the case where generators do in fact return a value
        generator = random.choices(self.generators, self.weights)[0]
        result = await generator(itgs, ctx)

        if result is not None:
            return result

        removed_index = self.generators.index(generator)
        remaining = (
            self.generators[:removed_index] + self.generators[removed_index + 1 :]
        )
        remaining_weights = (
            None
            if self.weights is None
            else self.weights[:removed_index] + self.weights[removed_index + 1 :]
        )

        while remaining:
            item = random.choices(remaining, remaining_weights)[0]
            result = await item(itgs, ctx)
            if result is not None:
                return result

            removed_index = remaining.index(item)
            remaining = remaining[:removed_index] + remaining[removed_index + 1 :]
            remaining_weights = (
                None
                if remaining_weights is None
                else remaining_weights[:removed_index]
                + remaining_weights[removed_index + 1 :]
            )

        return None


class GreedyGenerator:
    """Selects from the first random generator in the list which gives a result, without
    concurrency
    """

    def __init__(self, generators: List[HomescreenHeadlineGenerator]) -> None:
        self.generators = generators

    def precheck(self, ctx: HomescreenCopyContext) -> bool:
        return any(generator.precheck(ctx) for generator in self.generators)

    async def __call__(
        self, itgs: Itgs, ctx: HomescreenCopyContext
    ) -> Optional[HomescreenHeadline]:
        for generator in self.generators:
            if result := await generator(itgs, ctx):
                return result
        return None


_session_start_generator = GreedyGenerator(
    [
        SplitHeadlineSubheadlineGenerator(
            "goal_one_session_away",
            headline_generator=_session_start_headline_only,
            subheadline_generator=GoalOneSessionAwaySubheadlineOnlyGenerator(),
        ),
        SplitHeadlineSubheadlineGenerator(
            "goal_two_sessions_away",
            headline_generator=_session_start_headline_only,
            subheadline_generator=GoalTwoSessionsAwaySubheadlineOnlyGenerator(),
        ),
        SimpleWeightedRandomGenerator(
            [
                SplitHeadlineSubheadlineGenerator(
                    "session_start_quote_filler",
                    headline_generator=_session_start_headline_only,
                    subheadline_generator=_quote_subheadlines_only,
                ),
                SplitHeadlineSubheadlineGenerator(
                    "session_start_tip_filler",
                    headline_generator=_session_start_headline_only,
                    subheadline_generator=_tip_subheadlines_only,
                ),
            ],
            [
                len(_quote_subheadlines_only.generators),
                len(_tip_subheadlines_only.generators),
            ],
        ),
    ]
)

_session_end_generator = GreedyGenerator(
    [
        _class_milestones,
        _anniversaries,
        _streaks,
        GoalCompleteGenerator(),
        SplitHeadlineSubheadlineGenerator(
            "session_end_filler",
            headline_generator=_session_end_headline_only,
            subheadline_generator=_session_end_subheadlines_only,
        ),
    ]
)


async def generate_new_headline(
    itgs: Itgs, ctx: HomescreenCopyContext
) -> HomescreenHeadline:
    """Selects a new headline within the given context. This doesn't handle caching
    the value so we don't regenerate it excessively.
    """
    if ctx.client_variant == "session_start":
        res = await _session_start_generator(itgs, ctx)
        assert res
        return res
    elif ctx.client_variant == "session_end":
        res = await _session_end_generator(itgs, ctx)
        assert res
        return res
    else:
        raise AssertionError(f"Unknown client variant: {ctx.client_variant}")


if __name__ == "__main__":

    async def _main():
        user_sub = input("user sub: ")
        client_variant_raw = input("client variant: ")

        assert client_variant_raw in ("session_start", "session_end")
        client_variant = cast(HomescreenClientVariant, client_variant_raw)
        logger.info("GATHERING PREREQUISITES")
        async with Itgs() as itgs:
            conn = await itgs.conn()
            cursor = conn.cursor("none")
            show_tz = await get_user_timezone(itgs, user_sub=user_sub)
            show_at = time.time()
            show_unix_date = unix_dates.unix_timestamp_to_unix_date(show_at, tz=show_tz)
            response = await cursor.executeunified3(
                (
                    (
                        "SELECT given_name, created_at FROM users WHERE sub=?",
                        (user_sub,),
                    ),
                    (
                        "SELECT 1 FROM users, user_journeys WHERE users.sub=? AND user_journeys.user_id = users.id AND user_journeys.created_at_unix_date=?",
                        (user_sub, show_unix_date),
                    ),
                )
            )
            assert response[0].results
            given_name = cast(str, response[0].results[0][0])
            created_at = cast(float, response[0].results[0][1])
            taken_class = bool(response[1].results)
            streak = await read_user_streak(itgs, sub=user_sub, prefer="model")
            ctx = HomescreenCopyContext(
                user_sub=user_sub,
                given_name=given_name,
                client_variant=client_variant,
                taken_class_today=taken_class,
                user_created_at=created_at,
                show_at=show_at,
                show_tz=show_tz,
                streak=streak,
            )

            logger.info("GENERATING HEADLINE")
            headline = await generate_new_headline(itgs, ctx)
            print(f"{headline=}")

    asyncio.run(_main())
