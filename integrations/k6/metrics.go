package edgelens

import (
	"go.k6.io/k6/js/modules"
	"go.k6.io/k6/metrics"
)

// edgelensMetrics holds the per-VU metric registrations. Both are
// trend metrics so k6 thresholds can reference avg/p(95)/p(99) etc.
type edgelensMetrics struct {
	InferenceFPS       *metrics.Metric
	InferenceLatencyMS *metrics.Metric
}

func registerMetrics(vu modules.VU) *edgelensMetrics {
	reg := vu.InitEnv().Registry
	return &edgelensMetrics{
		InferenceFPS: reg.MustNewMetric(
			"inference_fps", metrics.Trend,
		),
		InferenceLatencyMS: reg.MustNewMetric(
			"inference_latency_ms", metrics.Trend, metrics.Time,
		),
	}
}
