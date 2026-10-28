package edgelens

import (
	"encoding/json"
	"fmt"
	"time"
)

// Session is what the JS side gets back from createSession() / resume().
type Session struct {
	ID     string `js:"id"`
	status string

	client *Client
	module *Module
}

// WaitReadyOptions controls the wait_ready poll loop.
type WaitReadyOptions struct {
	Timeout      int     `js:"timeout"`      // seconds; default 300
	PollInterval float64 `js:"pollInterval"` // seconds; default 2
}

// WaitReady blocks until the session reaches status=ready.
func (s *Session) WaitReady(opts WaitReadyOptions) error {
	if opts.Timeout == 0 {
		opts.Timeout = 300
	}
	if opts.PollInterval == 0 {
		opts.PollInterval = 2.0
	}
	deadline := time.Now().Add(time.Duration(opts.Timeout) * time.Second)
	for time.Now().Before(deadline) {
		var resp sessionResponse
		if err := s.client.doJSON("GET", "/v1/sessions/"+s.ID, nil, &resp); err != nil {
			return err
		}
		s.status = resp.Status
		switch resp.Status {
		case "ready":
			return nil
		case "error", "expired", "released":
			return fmt.Errorf("session %s reached terminal status %q before ready: %s",
				s.ID, resp.Status, resp.Error)
		}
		time.Sleep(time.Duration(opts.PollInterval * float64(time.Second)))
	}
	return fmt.Errorf("session %s did not reach ready within %ds", s.ID, opts.Timeout)
}

// Release releases the device.
func (s *Session) Release() error {
	return s.client.doJSON("DELETE", "/v1/sessions/"+s.ID, nil, nil)
}

// Device returns the per-session device operations object.
func (s *Session) Device() *Device {
	return &Device{session: s}
}

// Device is what the JS side gets at `session.device`.
type Device struct {
	session *Session
}

// DeployFile is one uploaded file. Data is the ArrayBuffer returned by
// k6's init-context open(path, "b"); a string or []byte also works.
type DeployFile struct {
	Name string `js:"name"`
	Data any    `js:"data"`
}

// DeployOptions is what JS passes to device.deploy({...}).
type DeployOptions struct {
	Model  DeployFile   `js:"model"`
	Config DeployFile   `js:"config"`
	Files  []DeployFile `js:"files"`
}

// Deploy uploads a model, plus optional config and extra files, to the
// camera as multipart/form-data.
func (d *Device) Deploy(opts DeployOptions) error {
	if opts.Model.Data == nil {
		return fmt.Errorf("deploy requires model: { name, data }")
	}
	parts := []filePart{{field: "model", file: opts.Model}}
	if opts.Config.Data != nil {
		parts = append(parts, filePart{field: "config", file: opts.Config})
	}
	for i, f := range opts.Files {
		parts = append(parts, filePart{field: fmt.Sprintf("file_%d", i), file: f})
	}
	return d.session.client.doMultipart(
		"/v1/sessions/"+d.session.ID+"/deploy", parts, nil,
	)
}

// Inference returns the per-device inference controller.
func (d *Device) Inference() *Inference {
	return &Inference{device: d}
}

// Exec runs a shell command on the camera via SSH.
type ExecOptions struct {
	Timeout float64 `js:"timeout"` // seconds
}

func (d *Device) Exec(command string, opts ExecOptions) (*ExecResult, error) {
	if opts.Timeout == 0 {
		opts.Timeout = 60
	}
	body, _ := json.Marshal(map[string]any{
		"command": command,
		"timeout": opts.Timeout,
	})
	var resp ExecResult
	err := d.session.client.doJSON(
		"POST", "/v1/sessions/"+d.session.ID+"/exec", body, &resp,
	)
	return &resp, err
}

// ExecResult is what JS sees from device.exec().
type ExecResult struct {
	Stdout   string `json:"stdout" js:"stdout"`
	Stderr   string `json:"stderr" js:"stderr"`
	ExitCode int    `json:"exit_code" js:"exitCode"`
}

// Success is sugar matching the Python SDK's `.success` property.
func (r *ExecResult) Success() bool { return r.ExitCode == 0 }
