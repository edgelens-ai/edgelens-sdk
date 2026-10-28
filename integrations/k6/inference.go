package edgelens

import (
	"encoding/json"
	"fmt"
	"time"

	"go.k6.io/k6/metrics"
)

// Inference is what JS gets at `device.inference`.
type Inference struct {
	device *Device
}

// Start kicks off the built-in inference engine. stock-os only.
func (i *Inference) Start() error {
	return i.device.session.client.doJSON(
		"POST", "/v1/sessions/"+i.device.session.ID+"/inference/start", nil, nil,
	)
}

// Stop halts inference.
func (i *Inference) Stop() error {
	return i.device.session.client.doJSON(
		"POST", "/v1/sessions/"+i.device.session.ID+"/inference/stop", nil, nil,
	)
}

// PercentileStats is a fps/latency rollup.
type PercentileStats struct {
	Avg float64 `json:"avg" js:"avg"`
	P50 float64 `json:"p50" js:"p50"`
	P95 float64 `json:"p95" js:"p95"`
	P99 float64 `json:"p99" js:"p99"`
}

// Stats is what JS gets from inference.stats() / .run().
type Stats struct {
	FPS            PercentileStats `json:"fps" js:"fps"`
	LatencyMS      PercentileStats `json:"latency_ms" js:"latency_ms"`
	DetectionCount int             `json:"detection_count" js:"detection_count"`
	DurationS      float64         `json:"duration_s" js:"duration_s"`
}

// Stats returns one snapshot and emits k6 metrics.
func (i *Inference) Stats() (*Stats, error) {
	var s Stats
	if err := i.device.session.client.doJSON(
		"GET", "/v1/sessions/"+i.device.session.ID+"/inference/stats", nil, &s,
	); err != nil {
		return nil, err
	}
	i.emit(&s)
	return &s, nil
}

// Run blocks for `duration` seconds and returns aggregated stats.
func (i *Inference) Run(duration float64) (*Stats, error) {
	body, _ := json.Marshal(map[string]any{
		"duration_s":      duration,
		"collect_frames": false,
	})
	var s Stats
	if err := i.device.session.client.doJSON(
		"POST", "/v1/sessions/"+i.device.session.ID+"/inference/results", body, &s,
	); err != nil {
		return nil, err
	}
	i.emit(&s)
	return &s, nil
}

// emit pushes one Sample per metric so k6's threshold engine sees them.
func (i *Inference) emit(s *Stats) {
	mod := i.device.session.module
	if mod == nil || mod.vu == nil || mod.metrics == nil {
		return // testing path or pre-init; nothing to emit to.
	}
	state := mod.vu.State()
	if state == nil {
		return
	}
	m := mod.metrics
	now := time.Now()
	ctx := mod.vu.Context()
	tags := state.Tags.GetCurrentValues().Tags.With("session_id", i.device.session.ID)
	metrics.PushIfNotDone(ctx, state.Samples, metrics.ConnectedSamples{
		Samples: []metrics.Sample{
			{
				TimeSeries: metrics.TimeSeries{Metric: m.InferenceFPS, Tags: tags},
				Time:       now,
				Value:      s.FPS.Avg,
			},
			{
				TimeSeries: metrics.TimeSeries{Metric: m.InferenceLatencyMS, Tags: tags},
				Time:       now,
				Value:      s.LatencyMS.P95,
			},
		},
		Time: now,
	})
}

// String for "%v" prints. Mostly useful for debugging from k6 scripts.
func (s *Stats) String() string {
	return fmt.Sprintf("Stats{fps.avg=%.1f, latency_p95=%.1fms, detections=%d}",
		s.FPS.Avg, s.LatencyMS.P95, s.DetectionCount)
}
