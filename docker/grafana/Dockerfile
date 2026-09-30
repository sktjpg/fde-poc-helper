# Grafana's all-in-one OpenTelemetry backend: an OTel Collector receiving OTLP, Prometheus
# (metrics), Tempo (traces), Loki (logs) and Grafana, in one container for development.
# The agent dashboard is baked in rather than bind-mounted so the image also works when
# Docker runs on another machine.
FROM grafana/otel-lgtm:latest
COPY dashboards.yaml /otel-lgtm/grafana/conf/provisioning/dashboards/agent.yaml
COPY agent-dashboard.json /otel-lgtm/agent-dashboard.json
