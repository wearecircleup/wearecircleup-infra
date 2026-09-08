from __future__ import annotations

import os
from pathlib import Path

from diagrams import Cluster, Diagram
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.engagement import SimpleEmailServiceSes
from diagrams.aws.integration import Eventbridge, SimpleQueueServiceSqs
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock, Textract
from diagrams.aws.network import APIGateway
from diagrams.aws.security import SecretsManager
from diagrams.aws.storage import S3


ROOT = Path(__file__).resolve().parent
GRAPHVIZ_BIN = Path(r"C:\Program Files\Graphviz\bin")

if GRAPHVIZ_BIN.exists():
    os.environ["PATH"] = str(GRAPHVIZ_BIN) + os.pathsep + os.environ.get("PATH", "")


def graph(direction: str) -> dict[str, object]:
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


def render_runtime_overview() -> None:
    with Diagram(
        "Circle Up - AWS Runtime Overview",
        filename=str(ROOT / "01-runtime-overview"),
        **graph("LR"),
    ):
        secret = SecretsManager("Shared runtime secret")
        logs = Cloudwatch("Lambda logs")
        ses = SimpleEmailServiceSes("SES")
        bedrock = Bedrock("Bedrock")
        textract = Textract("Textract")

        with Cluster("API ingress"):
            eventbrite_api = APIGateway("Eventbrite API")
            eventbrite_api_lambda = Lambda("eventbrite_api")
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
            background_reviewer = Lambda("background_check_reviewer")

        with Cluster("Data plane"):
            eventbrite_orders = Dynamodb("Eventbrite orders")
            minor_jobs = Dynamodb("Minor auth jobs")
            youform_submissions = Dynamodb("YouForm submissions")
            volunteer_proposals = Dynamodb("Volunteer proposals")
            background_submissions = Dynamodb("Background submissions")
            background_reviews = Dynamodb("Background reviews")
            signatures = S3("Minor auth signatures")
            background_files = S3("Background PDFs")
            public_assets = S3("Public assets")

        eventbrite_api >> eventbrite_api_lambda
        eventbrite_webhook_api >> eventbrite_webhook
        youform_api >> youform_webhook

        eventbrite_api_lambda >> secret
        eventbrite_webhook >> secret
        youform_webhook >> secret
        minor_validator >> secret
        background_reviewer >> secret

        eventbrite_webhook >> eventbrite_orders
        eventbrite_webhook >> minor_queue >> minor_validator >> minor_jobs
        minor_validator >> youform_submissions

        reminder_rule >> reminder
        reminder >> eventbrite_orders
        reminder >> minor_jobs
        reminder >> ses

        youform_webhook >> youform_submissions
        youform_webhook >> volunteer_proposals
        youform_webhook >> background_submissions
        youform_webhook >> signatures
        youform_webhook >> background_files
        youform_webhook >> minor_jobs
        youform_webhook >> background_queue
        youform_webhook >> ses

        background_queue >> background_reviewer
        background_reviewer >> background_files
        background_reviewer >> background_submissions
        background_reviewer >> background_reviews
        background_reviewer >> bedrock
        background_reviewer >> textract
        background_reviewer >> ses

        public_assets >> ses
        [
            eventbrite_api_lambda,
            eventbrite_webhook,
            youform_webhook,
            minor_validator,
            reminder,
            background_reviewer,
        ] >> logs


def render_ingress_and_handlers() -> None:
    with Diagram(
        "Circle Up - AWS Ingress And Handlers",
        filename=str(ROOT / "02-ingress-and-handlers"),
        **graph("LR"),
    ):
        secret = SecretsManager("Shared runtime secret")
        logs = Cloudwatch("Lambda logs")

        with Cluster("Studio API"):
            eventbrite_api = APIGateway("Eventbrite API")
            eventbrite_api_lambda = Lambda("eventbrite_api")

        with Cluster("External webhooks"):
            eventbrite_webhook_api = APIGateway("Eventbrite order webhook")
            eventbrite_webhook = Lambda("eventbrite_order_webhook")
            youform_api = APIGateway("YouForm webhook")
            youform_webhook = Lambda("youform_webhook")

        eventbrite_api >> eventbrite_api_lambda
        eventbrite_webhook_api >> eventbrite_webhook
        youform_api >> youform_webhook

        [eventbrite_api_lambda, eventbrite_webhook, youform_webhook] >> secret
        [eventbrite_api_lambda, eventbrite_webhook, youform_webhook] >> logs


def render_async_processing() -> None:
    with Diagram(
        "Circle Up - AWS Async Processing",
        filename=str(ROOT / "03-async-processing"),
        **graph("LR"),
    ):
        ses = SimpleEmailServiceSes("SES")
        secret = SecretsManager("Shared runtime secret")

        with Cluster("Minor authorization"):
            minor_queue = SimpleQueueServiceSqs("Minor auth queue")
            minor_validator = Lambda("minor_authorization_validator")
            minor_jobs = Dynamodb("Minor auth jobs")
            youform_submissions = Dynamodb("YouForm submissions")
            eventbrite_orders = Dynamodb("Eventbrite orders")
            reminder_rule = Eventbridge("Daily reminder")
            reminder = Lambda("minor_authorization_reminder")

        with Cluster("Background review"):
            background_queue = SimpleQueueServiceSqs("Background review queue")
            background_reviewer = Lambda("background_check_reviewer")
            background_files = S3("Background PDFs")
            background_submissions = Dynamodb("Background submissions")
            background_reviews = Dynamodb("Background reviews")
            bedrock = Bedrock("Bedrock")
            textract = Textract("Textract")

        minor_queue >> minor_validator
        minor_validator >> minor_jobs
        minor_validator >> youform_submissions
        minor_validator >> secret

        reminder_rule >> reminder
        reminder >> eventbrite_orders
        reminder >> minor_jobs
        reminder >> ses

        background_queue >> background_reviewer
        background_reviewer >> background_files
        background_reviewer >> background_submissions
        background_reviewer >> background_reviews
        background_reviewer >> bedrock
        background_reviewer >> textract
        background_reviewer >> ses
        background_reviewer >> secret


def render_data_and_ai() -> None:
    with Diagram(
        "Circle Up - AWS Data And AI Dependencies",
        filename=str(ROOT / "04-data-and-ai"),
        **graph("LR"),
    ):
        youform_webhook = Lambda("youform_webhook")
        eventbrite_webhook = Lambda("eventbrite_order_webhook")
        minor_validator = Lambda("minor_authorization_validator")
        background_reviewer = Lambda("background_check_reviewer")

        eventbrite_orders = Dynamodb("Eventbrite orders")
        minor_jobs = Dynamodb("Minor auth jobs")
        youform_submissions = Dynamodb("YouForm submissions")
        volunteer_proposals = Dynamodb("Volunteer proposals")
        background_submissions = Dynamodb("Background submissions")
        background_reviews = Dynamodb("Background reviews")
        signatures = S3("Minor auth signatures")
        background_files = S3("Background PDFs")
        ses = SimpleEmailServiceSes("SES")
        bedrock = Bedrock("Bedrock")
        textract = Textract("Textract")

        eventbrite_webhook >> eventbrite_orders
        eventbrite_webhook >> minor_jobs
        youform_webhook >> youform_submissions
        youform_webhook >> volunteer_proposals
        youform_webhook >> background_submissions
        youform_webhook >> signatures
        youform_webhook >> background_files
        youform_webhook >> minor_jobs
        youform_webhook >> ses
        minor_validator >> minor_jobs
        minor_validator >> youform_submissions
        background_reviewer >> background_files
        background_reviewer >> background_submissions
        background_reviewer >> background_reviews
        background_reviewer >> bedrock
        background_reviewer >> textract
        background_reviewer >> ses


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    render_runtime_overview()
    render_ingress_and_handlers()
    render_async_processing()
    render_data_and_ai()
    print(f"Rendered diagrams in {ROOT}")


if __name__ == "__main__":
    main()
