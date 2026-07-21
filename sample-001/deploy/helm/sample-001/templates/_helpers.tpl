{{- define "sample-001.labels" -}}
app.kubernetes.io/part-of: sample-001
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
sample-001.example/render-only: "true"
{{- end }}
