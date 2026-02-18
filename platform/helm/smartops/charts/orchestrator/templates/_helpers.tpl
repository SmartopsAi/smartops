{{/*
Expand the name of the chart.
*/}}
{{- define "orchestrator.name" -}}
{{ .Chart.Name }}
{{- end }}

{{/*
Fullname helper: <release name>-<chart name>
*/}}
{{- define "orchestrator.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Common labels
*/}}
{{- define "orchestrator.labels" -}}
app.kubernetes.io/name: {{ include "orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
