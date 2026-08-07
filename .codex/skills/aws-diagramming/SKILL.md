---
name: aws-diagramming
description: Use when generating or updating AWS architecture diagrams in this repository so Codex uses AWS-specific icons and layout conventions, preferring the configured AWS diagram MCP server and falling back to project-local Python diagrams only when needed.
---

# AWS Diagramming

## Purpose and Scope

Use this skill when the task is to create or revise AWS architecture diagrams for this repository. Prefer the configured aws-diagram MCP server backed by awslabs.aws-diagram-mcp-server for normal diagram generation. Fall back to a direct Python script using the project-local diagrams package only when the MCP server is unavailable or the task needs lower-level control. The goal is AWS-specific diagrams that read clearly, use real AWS service icons, and follow recognizable structure patterns instead of generic boxes. This applies to both small diagrams and larger multi-service architectures.

## Checks / Steps

Confirm the expected output artifact and save path first. Keep generated files inside generated-diagrams/ unless the user asks for another location. Organize outputs into clear subfolders when the work grows, for example by domain, capability, or architecture family. Use explicit, lowercase, hyphenated file names such as event-processing/context.png, event-processing/runtime-flow.png, or web-platform/detail-api-edge.py. Ask Codex to use the aws-diagram MCP server first. When falling back to Python, run through uv from the current project. Use AWS imports from diagrams.aws.* whenever the component is an AWS service. Prefer simple left-to-right or top-to-bottom flow, whichever makes the message clearest. Use clusters when they improve comprehension, especially for patterns similar to Clustered Web Services or Event Processing on AWS. For larger architectures, group by domain, runtime boundary, account, VPC, environment, or processing stage instead of by arbitrary service type. If one diagram becomes crowded, split it into a small set of views such as context, runtime/dataflow, and detail rather than forcing everything onto one canvas. Name components with short, explicit labels and label flow lines when the meaning is not obvious from placement alone. Render the output and visually check for text overlap, line clutter, and ambiguous direction before finishing.

## Non-Negotiables

Keep generated artifacts repo-local. Use AWS icons for AWS services; do not substitute generic boxes when a suitable AWS icon exists in diagrams. Do not use pip; keep diagram dependencies and execution project-local through uv. Keep names and paths clear, stable, and modular under generated-diagrams/; avoid dumping unrelated outputs into one flat folder with vague names. Avoid text overlap, cramped labels, and crossing lines that make direction unclear. Group related services when that reduces visual noise, but do not add clusters that make the diagram heavier than the architecture itself. Do not force a complex system into one overloaded diagram when two or three clearer diagrams would communicate it better. Name nodes and flow lines clearly, keep flow direction ordered, and prefer redacted or synthetic labels over secrets, live account identifiers, or sensitive topology details unless the user explicitly asks for them.