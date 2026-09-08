from __future__ import annotations

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.engagement import Pinpoint, SimpleEmailServiceSes
from diagrams.aws.integration import Eventbridge, SimpleQueueServiceSqs
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Textract
from diagrams.aws.network import APIGateway
from diagrams.aws.security import SecretsManager
from diagrams.aws.storage import S3
from diagrams.custom import Custom
from diagrams.generic.blank import Blank


ROOT = Path(__file__).resolve().parent
ICON_ROOT = ROOT.parent / "icons"
GRAPHVIZ_BIN = Path(r"C:\Program Files\Graphviz\bin")

if GRAPHVIZ_BIN.exists():
    os.environ["PATH"] = str(GRAPHVIZ_BIN) + os.pathsep + os.environ.get("PATH", "")


def icon(name: str) -> str:
    return str((ICON_ROOT / name).resolve())


def streamlit_node() -> Custom:
    return Custom("Eventbrite Studio", icon("streamlit.png"))


def eventbrite_node() -> Custom:
    return Custom("Eventbrite", icon("eventbrite.png"))


def youform_node() -> Custom:
    return Custom("YouForm", icon("youform.png"))


def circleup_staff_node(label: str = "Circle Up staff") -> Custom:
    return Custom(label, icon("circleup.png"))


def participant_node(label: str = "Participants") -> Custom:
    return Custom(label, icon("participant.png"))


def volunteer_node(label: str = "Volunteers") -> Custom:
    return Custom(label, icon("volunteer.png"))


def form_node(label: str) -> Custom:
    return Custom(label, icon("youform.png"))


def domain_node(label: str, icon_name: str) -> Custom:
    return Custom(label, icon(icon_name))


def endpoint_node(label: str) -> Pinpoint:
    return Pinpoint(label)


def async_node(label: str) -> SimpleQueueServiceSqs:
    return SimpleQueueServiceSqs(label)


def common_graph(direction: str) -> dict[str, object]:
    return {
        "show": False,
        "outformat": "png",
        "direction": direction,
        "graph_attr": {
            "fontsize": "18",
            "pad": "0.35",
            "ranksep": "0.9",
            "nodesep": "0.45",
            "splines": "ortho",
        },
    }


def render_global_system_map() -> None:
    with Diagram(
        "Circle Up - Global System Map",
        filename=str(ROOT / "01-global-system-map"),
        **common_graph("LR"),
    ):
        streamlit = streamlit_node()
        eventbrite = eventbrite_node()
        youform = youform_node()
        staff = circleup_staff_node()
        participants = participant_node()
        volunteers = volunteer_node()

        with Cluster("AWS prod"):
            secret = SecretsManager("Shared runtime secret")
            logs = Cloudwatch("Lambda logs")
            ses = SimpleEmailServiceSes("SES")

            with Cluster("Interactive event management"):
                eventbrite_api = APIGateway("Eventbrite API")
                eventbrite_api_lambda = Lambda("eventbrite_api")

            with Cluster("Inbound webhooks"):
                eventbrite_webhook_api = APIGateway("Eventbrite order webhook")
                eventbrite_webhook = Lambda("eventbrite_order_webhook")
                youform_api = APIGateway("YouForm webhook")
                youform_webhook = Lambda("youform_webhook")

            with Cluster("Async processing"):
                minor_queue = SimpleQueueServiceSqs("Minor auth queue")
                minor_validator = Lambda("minor_authorization_validator")
                reminder_rule = Eventbridge("Daily reminder")
                reminder = Lambda("minor_authorization_reminder")
                background_queue = SimpleQueueServiceSqs("Background review queue")
                background_worker = Lambda("background_check_reviewer")

            with Cluster("Data and files"):
                eventbrite_orders = Dynamodb("Eventbrite orders")
                minor_jobs = Dynamodb("Minor auth jobs")
                youform_submissions = Dynamodb("YouForm submissions")
                volunteer_proposals = Dynamodb("Volunteer proposals")
                background_submissions = Dynamodb("Background submissions")
                background_reviews = Dynamodb("Background reviews")
                signatures = S3("Minor auth signatures")
                background_files = S3("Background PDFs")
                public_assets = S3("Public assets")

        staff >> streamlit >> Edge(label="HTTP") >> eventbrite_api >> eventbrite_api_lambda >> eventbrite
        eventbrite >> Edge(label="order webhook") >> eventbrite_webhook_api >> eventbrite_webhook
        participants >> Edge(label="minor auth forms") >> youform
        volunteers >> Edge(label="intake and uploads") >> youform
        youform >> Edge(label="HTTP webhook") >> youform_api >> youform_webhook

        eventbrite_api_lambda >> secret
        eventbrite_webhook >> secret
        youform_webhook >> secret
        minor_validator >> secret
        background_worker >> secret

        eventbrite_webhook >> eventbrite_orders
        eventbrite_webhook >> minor_queue >> minor_validator >> minor_jobs
        minor_validator >> youform_submissions
        reminder_rule >> reminder
        reminder >> minor_jobs
        reminder >> eventbrite_orders
        reminder >> ses

        youform_webhook >> youform_submissions
        youform_webhook >> volunteer_proposals
        youform_webhook >> background_submissions
        youform_webhook >> signatures
        youform_webhook >> background_files
        youform_webhook >> minor_jobs
        youform_webhook >> background_queue
        youform_webhook >> ses

        background_queue >> background_worker
        background_worker >> background_files
        background_worker >> background_submissions
        background_worker >> background_reviews
        background_worker >> Bedrock("Bedrock")
        background_worker >> Textract("Textract")
        background_worker >> ses
        public_assets >> Blank("Email branding")

        [
            eventbrite_api_lambda,
            eventbrite_webhook,
            youform_webhook,
            minor_validator,
            reminder,
            background_worker,
        ] >> logs


def render_interface_ownership() -> None:
    with Diagram(
        "Circle Up - Interface Ownership And Overlap",
        filename=str(ROOT / "02-interface-ownership-overlap"),
        **common_graph("LR"),
    ):
        staff = circleup_staff_node("Ops and organizers")
        participants = participant_node()
        volunteers = volunteer_node()
        streamlit = streamlit_node()
        eventbrite = eventbrite_node()
        youform = youform_node()
        streamlit_create = endpoint_node("Studio create event")
        streamlit_delete = endpoint_node("Studio delete event")
        eventbrite_webhook = endpoint_node("Eventbrite order webhook")
        youform_webhook = endpoint_node("YouForm webhook")
        minor_async = async_node("Minor auth async")
        background_async = async_node("Background review async")

        with Cluster("Interfaces"):
            staff >> streamlit >> streamlit_create
            streamlit >> streamlit_delete
            eventbrite >> eventbrite_webhook
            participants >> youform
            volunteers >> youform
            youform >> youform_webhook
            eventbrite_webhook >> minor_async
            youform_webhook >> background_async

        with Cluster("Owned domains"):
            lifecycle = domain_node("Event lifecycle", "eventbrite.png")
            venues = domain_node("Venue catalog", "eventbrite.png")
            minors = domain_node("Minor authorization", "youform.png")
            volunteer_intake = domain_node("Volunteer intake", "volunteer.png")
            reviews = domain_node("Background review", "volunteer.png")
            notifications = SimpleEmailServiceSes("Notifications")

        streamlit_create >> lifecycle
        streamlit_create >> venues
        streamlit_delete >> lifecycle
        eventbrite_webhook >> minors
        youform_webhook >> minors
        youform_webhook >> volunteer_intake
        youform_webhook >> reviews
        youform_webhook >> notifications
        minor_async >> minors
        minor_async >> notifications
        background_async >> reviews
        background_async >> notifications


def render_streamlit_create_flow() -> None:
    with Diagram(
        "Circle Up - Streamlit Create Event Flow",
        filename=str(ROOT / "03-streamlit-create-event-flow"),
        **common_graph("LR"),
    ):
        staff = circleup_staff_node("Organizer")
        streamlit = streamlit_node()
        eventbrite = eventbrite_node()
        eventbrite_api = APIGateway("Eventbrite API")
        api_lambda = Lambda("eventbrite_api")

        venues = endpoint_node("GET /venues\nPOST /venues\nPATCH /venues/{venue_id}")
        instantiate = endpoint_node("POST /event-instantiations")
        image_request = endpoint_node("GET /events/{id}/image/upload-request")
        image_binary = endpoint_node("POST /events/{id}/image/upload-binary")
        image_complete = endpoint_node("POST /events/{id}/image/complete")
        publish = endpoint_node("POST /event-instantiations/{id}/publish")

        staff >> streamlit
        streamlit >> venues >> eventbrite_api
        streamlit >> instantiate >> eventbrite_api
        streamlit >> image_request >> eventbrite_api
        streamlit >> image_binary >> eventbrite_api
        streamlit >> image_complete >> eventbrite_api
        streamlit >> publish >> eventbrite_api
        eventbrite_api >> api_lambda >> eventbrite


def render_streamlit_delete_flow() -> None:
    with Diagram(
        "Circle Up - Streamlit Delete Event Flow",
        filename=str(ROOT / "04-streamlit-delete-event-flow"),
        **common_graph("LR"),
    ):
        staff = circleup_staff_node("Organizer")
        streamlit = streamlit_node()
        eventbrite = eventbrite_node()
        eventbrite_api = APIGateway("Eventbrite API")
        api_lambda = Lambda("eventbrite_api")

        list_events = endpoint_node("GET /events")
        get_event = endpoint_node("GET /events/{id}")
        get_attendance = endpoint_node("GET /events/{id}/attendance")
        delete_event = endpoint_node("DELETE /events/{id}?confirm=true")

        staff >> streamlit
        streamlit >> list_events >> eventbrite_api
        streamlit >> get_event >> eventbrite_api
        streamlit >> get_attendance >> eventbrite_api
        streamlit >> delete_event >> eventbrite_api
        eventbrite_api >> api_lambda >> eventbrite


def render_eventbrite_webhook_flow() -> None:
    with Diagram(
        "Circle Up - Eventbrite Order Webhook",
        filename=str(ROOT / "05-eventbrite-order-webhook-flow"),
        **common_graph("LR"),
    ):
        eventbrite = eventbrite_node()

        with Cluster("Entry point"):
            api = APIGateway("POST /webhooks/eventbrite/order-place")
            webhook = Lambda("eventbrite_order_webhook")

        with Cluster("Work done inside the request"):
            secret = SecretsManager("Shared runtime secret")
            order_lookup = endpoint_node("GET order")
            event_lookup = endpoint_node("GET event")
            venue_lookup = endpoint_node("GET venue")
            attendees_lookup = endpoint_node("GET order attendees")
            orders = Dynamodb("Eventbrite orders")
            minor_queue = SimpleQueueServiceSqs("Minor auth queue")

        eventbrite >> api >> webhook
        webhook >> secret
        webhook >> order_lookup >> eventbrite
        webhook >> event_lookup >> eventbrite
        webhook >> venue_lookup >> eventbrite
        webhook >> attendees_lookup >> eventbrite
        webhook >> orders
        webhook >> minor_queue


def render_youform_webhook_flow() -> None:
    with Diagram(
        "Circle Up - YouForm Webhook Routing",
        filename=str(ROOT / "06-youform-webhook-routing"),
        **common_graph("LR"),
    ):
        participants = participant_node("Participant submitter")
        volunteers = volunteer_node("Volunteer submitter")
        youform = youform_node()
        secret = SecretsManager("Shared runtime secret")
        ses = SimpleEmailServiceSes("SES")
        api = APIGateway("POST /webhooks/youform")
        webhook = Lambda("youform_webhook")

        minor_forms = form_node("Minor authorization form_id")
        volunteer_forms = form_node("Volunteer proposal form_id")
        bg_forms = form_node("Background check form_id")
        review_forms = form_node("Internal review form_id")

        submissions = Dynamodb("YouForm submissions")
        volunteer_proposals = Dynamodb("Volunteer proposals")
        background_submissions = Dynamodb("Background submissions")
        jobs = Dynamodb("Minor auth jobs")
        signatures = S3("Minor auth signatures")
        background_files = S3("Background PDFs")
        background_queue = SimpleQueueServiceSqs("Background review queue")

        participants >> youform
        volunteers >> youform
        youform >> api >> webhook
        webhook >> secret
        webhook >> minor_forms >> submissions
        webhook >> minor_forms >> signatures
        webhook >> minor_forms >> jobs
        webhook >> volunteer_forms >> volunteer_proposals
        webhook >> volunteer_forms >> ses
        webhook >> bg_forms >> background_submissions
        webhook >> bg_forms >> background_files
        webhook >> bg_forms >> background_queue
        webhook >> review_forms >> background_submissions


def render_minor_authorization_flow() -> None:
    with Diagram(
        "Circle Up - Minor Authorization Async Flow",
        filename=str(ROOT / "07-minor-authorization-flow"),
        **common_graph("LR"),
    ):
        eventbrite = eventbrite_node()
        youform = youform_node()
        eventbrite_webhook = Lambda("eventbrite_order_webhook")
        validator = Lambda("minor_authorization_validator")
        reminder_rule = Eventbridge("Daily reminder")
        reminder = Lambda("minor_authorization_reminder")

        orders = Dynamodb("Eventbrite orders")
        jobs = Dynamodb("Minor auth jobs")
        submissions = Dynamodb("YouForm submissions")
        queue = SimpleQueueServiceSqs("Minor auth queue")
        ses = SimpleEmailServiceSes("SES")

        eventbrite >> eventbrite_webhook >> orders
        eventbrite_webhook >> Edge(label="one message per minor") >> queue >> validator
        validator >> Edge(label="create job") >> jobs
        validator >> Edge(label="search by email + event") >> submissions
        youform >> Edge(label="form webhook") >> submissions
        submissions >> Edge(label="reconcile authorized forms") >> jobs
        reminder_rule >> reminder
        reminder >> Edge(label="query missing_form") >> jobs
        reminder >> Edge(label="refresh order snapshot") >> orders
        reminder >> ses


def render_background_check_flow() -> None:
    with Diagram(
        "Circle Up - Background Check Async Flow",
        filename=str(ROOT / "08-background-check-flow"),
        **common_graph("LR"),
    ):
        participants = volunteer_node()
        youform = youform_node()
        youform_webhook = Lambda("youform_webhook")
        reviewer = Lambda("background_check_reviewer")
        queue = SimpleQueueServiceSqs("Background review queue")
        submissions = Dynamodb("Background submissions")
        reviews = Dynamodb("Background reviews")
        files = S3("Background PDFs")
        ses = SimpleEmailServiceSes("SES")
        bedrock = Bedrock("Bedrock")
        textract = Textract("Textract")

        participants >> youform >> youform_webhook
        youform_webhook >> submissions
        youform_webhook >> files
        youform_webhook >> Edge(label="one message per document") >> queue >> reviewer
        reviewer >> files
        reviewer >> reviews
        reviewer >> Edge(label="cedula extraction") >> bedrock
        reviewer >> Edge(label="certificate OCR") >> textract
        reviewer >> ses


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    render_global_system_map()
    render_interface_ownership()
    render_streamlit_create_flow()
    render_streamlit_delete_flow()
    render_eventbrite_webhook_flow()
    render_youform_webhook_flow()
    render_minor_authorization_flow()
    render_background_check_flow()
    print(f"Rendered diagrams in {ROOT}")


if __name__ == "__main__":
    main()
