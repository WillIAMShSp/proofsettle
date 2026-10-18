"""Which shipments a caller may see: shipments belong to accounts, not to the app.

A shipment belongs to the buyer account that created it (`created_by`, a Supabase user id)
and, if it names one, the recipient: the manufacturer's account email. Only those accounts,
and Reviewers (who rule on disputes for everyone), can see it; to anyone else it doesn't
exist (404, and it's missing from the list). A shipment with no owner, such as a freshly
loaded demo seed, is seen by no account until one is assigned (python -m app.ownership).

A dev login (PROOFSETTLE_DEV_AUTH) has a role but no identity, so it sees everything.
Roles still decide what a caller may do (app.workflow); this only decides what they see.
"""

from app.auth import Caller
from app.models import Shipment
from app.workflow import Actor


def can_see(s: Shipment, caller: Caller) -> bool:
    if caller.actor is Actor.REVIEWER:
        return True
    if caller.user_id is None and caller.email is None:
        return True
    is_creator = caller.user_id is not None and caller.user_id == s.created_by
    is_recipient = caller.email is not None and caller.email == s.recipient_email
    return is_creator or is_recipient
