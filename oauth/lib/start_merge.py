from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from itgs import Itgs
import auth as std_auth
import oauth.lib.start_merge_auth
from users.me.routes.update_notification_time import DayOfWeek


class EmailForConflict(BaseModel):
    email_address: str = Field(description="The email address")
    suppressed: bool = Field(
        description="If true, we cannot send emails to this address due to e.g. a past complaint"
    )
    verified: bool = Field(
        description="If true, we are satisfied that the user has access to this email address"
    )
    enabled: bool = Field(
        description="If true, the user is ok receiving emails at this address"
    )


class PhoneForConflict(BaseModel):
    phone_number: str = Field(description="The phone number")
    suppressed: bool = Field(
        description="If true, we cannot send SMS to this number due to e.g. a Stop message"
    )
    verified: bool = Field(
        description="If true, we are satisfied that the user has access to this phone number"
    )
    enabled: bool = Field(
        description="If true, the user is ok receiving SMS at this number"
    )


class DailyReminderSettingsForConflict(BaseModel):
    days_of_week: List[DayOfWeek] = Field(
        description="the days of the week they receive notifications on this channel",
        unique_items=True,  # type: ignore
    )
    start_time: int = Field(
        description="The earliest they receive notifications in seconds from midnight"
    )
    end_time: int = Field(
        description="The latest they receive notifications in seconds from midnight"
    )


class OauthEmailConflictInfo(BaseModel):
    original: List[EmailForConflict] = Field(
        description="The emails associated with the original user"
    )
    merging: List[EmailForConflict] = Field(
        description="The emails associated with the merging user"
    )
    original_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the original user"
    )
    merging_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the merging user"
    )


class OauthPhoneConflictInfo(BaseModel):
    original: List[PhoneForConflict] = Field(
        description="The phones associated with the original user"
    )
    merging: List[PhoneForConflict] = Field(
        description="The phones associated with the merging user"
    )
    original_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the original user"
    )
    merging_settings: DailyReminderSettingsForConflict = Field(
        description="The notification settings for the merging user"
    )


class OauthMergeConfirmationRequiredDetails(BaseModel):
    email: Optional[OauthEmailConflictInfo] = Field(
        description=(
            "The email conflict which need to be resolved. An email conflict "
            "is when both accounts are receiving email notifications, since the "
            "user probably only wants to receive notifications at one address. "
            "When the user confirms the merge they will need to select which email "
            "addresses should remain enabled."
        )
    )
    phone: Optional[OauthPhoneConflictInfo] = Field(
        description=(
            "The phone conflict which need to be resolved. A phone conflict "
            "is when both accounts are receiving SMS notifications, since the "
            "user probably only wants to receive notifications at one number. "
            "When the user confirms the merge they will need to select which phone "
            "numbers should remain enabled."
        )
    )
    merge_jwt: str = Field(
        description="The new merge JWT to use for the confirm_merge request."
    )


class OauthMergeResult(BaseModel):
    user_identity_uid: str = Field(
        description=(
            "The uid of the record in user_identities that the code corresponded to. "
            "This user identity may or may not correspond with the original sub; see "
            "the `result` field for details"
        )
    )
    result: Literal[
        "no_change_required",
        "created_and_attached",
        "trivial_merge",
        "confirmation_required",
        "requires_support",
    ] = Field(
        description=(
            "What action was taken immediately. The possibilities are:\n"
            "- `no_change_required`: the code was associated with a user identity already associated"
            " with the original user. For example, the user just tried to merge with the same identity"
            " they signed in with.\n"
            "- `created_and_attached`: the code corresponded to a provider sub that we didn't recognize,"
            " i.e., if this were the login flow we would have created a user. Instead of creating a user,"
            " we created a new user identity associating this provider sub with the original user.\n"
            "- `trivial_merge`: the code corresponded to a provider sub that we did recognize, and it was"
            " a different user than the original user that started the merge. However, one of the accounts"
            " had essentially no information, so we just merged the two accounts together.\n"
            "- `confirmation_required`: the code corresponded to a provider sub that we did recognize, and"
            " it was a different user than the original user that started the merge. There is nothing blocking"
            " a merge of the two accounts, but the merge may be destructive. The user needs to confirm which"
            " account we should prefer when information conflicts.\n"
            "- `requires_support`: the code corresponded to a provider sub that we did recognize, and it was"
            " a different user than the original user that started the merge. However, it is not possible to"
            " automatically merge these accounts. For example, both accounts might have a subscription. We will"
            " ping slack and the user should be contacted by support to resolve the conflict."
        )
    )
    conflict_details: Optional[OauthMergeConfirmationRequiredDetails] = Field(
        None,
        description=(
            "If the `result` is `confirmation_required`, this field will be populated with"
            " details about the conflict that the user needs to resolve"
        ),
    )


async def attempt_start_merge(
    itgs: Itgs,
    *,
    original_user: std_auth.SuccessfulAuthResult,
    merge: oauth.lib.start_merge_auth.SuccessfulAuthResult,
) -> OauthMergeResult:
    """Performs the core merge for the given original user authorized to perform
    the given merge.

    Args:
        itgs (Itgs): the integrations to (re)use
        original_user (std_auth.SuccessfulAuthResult): The user must provide valid
            authorization for the original user in the merge along with the merge
            JWT to avoid merge JWTs extending the duration of id tokens, which is
            not intended. This is the result of the standard auth flow.
        merge (oauth.lib.start_merge_auth.SuccessfulAuthResult): The user must provide
            proof they are allowed to perform the given merge. We will also use this
            for ensuring the example claims of the provider for the user identity are
            properly updated/initialized

    Returns:
        OauthMergeResult: The result of the operation
    """
    raise NotImplementedError()
