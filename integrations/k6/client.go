package edgelens

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"path/filepath"
	"time"

	"go.k6.io/k6/js/common"
)

// Client wraps the EdgeLens REST API for one VU.
type Client struct {
	apiKey  string
	baseURL string
	module  *Module
}

// CreateSessionOptions is what JS passes to client.createSession({...}).
type CreateSessionOptions struct {
	DeviceType   string `js:"deviceType"`
	OS           string `js:"os"`
	ImageVersion string `js:"imageVersion"`
	Timeout      int    `js:"timeout"`
}

// CreateSession allocates a device. Returns a Session that has not yet
// reached `ready` — call session.waitReady() before issuing device ops.
func (c *Client) CreateSession(opts CreateSessionOptions) (*Session, error) {
	if opts.DeviceType == "" {
		opts.DeviceType = "recamera-2002"
	}
	if opts.OS == "" {
		opts.OS = "stock-os"
	}
	if opts.Timeout == 0 {
		opts.Timeout = 3600
	}

	body, _ := json.Marshal(map[string]any{
		"device_type":   opts.DeviceType,
		"os":            opts.OS,
		"image_version": defaultStr(opts.ImageVersion, "latest"),
		"timeout":       opts.Timeout,
	})
	var resp sessionResponse
	if err := c.doJSON("POST", "/v1/sessions", body, &resp); err != nil {
		return nil, err
	}
	return &Session{
		ID:     resp.ID,
		status: resp.Status,
		client: c,
		module: c.module,
	}, nil
}

const (
	jsonTimeout = 30 * time.Second
	// uploadTimeout bounds a whole deploy upload; model files can be tens
	// of megabytes over a slow CI uplink.
	uploadTimeout = 10 * time.Minute
)

// doJSON sends a JSON request.
func (c *Client) doJSON(method, path string, body []byte, out any) error {
	req, err := http.NewRequest(method, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	if len(body) > 0 {
		req.Header.Set("Content-Type", "application/json")
	}
	return c.send(req, path, jsonTimeout, out)
}

type filePart struct {
	field string
	file  DeployFile
}

// doMultipart POSTs file parts as multipart/form-data. A part without a
// name uses its field name as the filename.
func (c *Client) doMultipart(path string, parts []filePart, out any) error {
	var body bytes.Buffer
	w := multipart.NewWriter(&body)
	for _, p := range parts {
		data, err := common.ToBytes(p.file.Data)
		if err != nil {
			return fmt.Errorf("deploy %s: %w", p.field, err)
		}
		name := p.file.Name
		if name == "" {
			name = p.field
		}
		fw, err := w.CreateFormFile(p.field, filepath.Base(name))
		if err != nil {
			return err
		}
		if _, err := fw.Write(data); err != nil {
			return err
		}
	}
	if err := w.Close(); err != nil {
		return err
	}
	req, err := http.NewRequest("POST", c.baseURL+path, &body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	return c.send(req, path, uploadTimeout, out)
}

func (c *Client) send(req *http.Request, path string, timeout time.Duration, out any) error {
	method := req.Method
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
	cl := &http.Client{Timeout: timeout}
	res, err := cl.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(res.Body)
	if res.StatusCode >= 400 {
		return fmt.Errorf("edgelens %s %s: %d %s", method, path, res.StatusCode, string(raw))
	}
	if out != nil && len(raw) > 0 {
		return json.Unmarshal(raw, out)
	}
	return nil
}

func defaultStr(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// sessionResponse is the on-the-wire shape returned by POST/GET /v1/sessions.
type sessionResponse struct {
	ID     string `json:"id"`
	Status string `json:"status"`
	Device *struct {
		Host        string `json:"host"`
		SSHUser     string `json:"ssh_user"`
		SSHPassword string `json:"ssh_password"`
		WebUI       string `json:"web_ui"`
		OS          string `json:"os"`
		MAC         string `json:"mac"`
	} `json:"device"`
	Error string `json:"error"`
}
