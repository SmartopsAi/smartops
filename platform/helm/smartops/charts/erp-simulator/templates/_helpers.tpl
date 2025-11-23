{{- define "erp-simulator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "erp-simulator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "erp-simulator.labels" -}}
app.kubernetes.io/name: {{ include "erp-simulator.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: smartops
{{- end }}

{{- define "erp-simulator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "erp-simulator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
