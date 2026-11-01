{{/* Коротке ім'я чарта */}}
{{- define "farm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Повне ім'я об'єктів: будується з імені релізу */}}
{{- define "farm.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/* Ім'я об'єктів бази даних */}}
{{- define "farm.postgresName" -}}
{{- printf "%s-postgres" (include "farm.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Мітка chart: назва-версія */}}
{{- define "farm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Мітки для вибору подів (selector) */}}
{{- define "farm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "farm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Повний набір міток для всіх об'єктів */}}
{{- define "farm.labels" -}}
helm.sh/chart: {{ include "farm.chart" . }}
{{ include "farm.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Образ застосунку */}}
{{- define "farm.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{/* Хост бази даних */}}
{{- define "farm.pgHost" -}}
{{- .Values.config.pgHost | default (include "farm.postgresName" .) }}
{{- end }}
