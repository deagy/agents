package model

import "time"

type Principal struct {
	Tenant         string
	Subject        string
	SessionVersion int64
	SessionHash    string
}

type Document struct {
	ID            string    `json:"id"`
	Tenant        string    `json:"-"`
	Subject       string    `json:"-"`
	Name          string    `json:"name"`
	MediaType     string    `json:"media_type,omitempty"`
	Size          int64     `json:"size,omitempty"`
	SHA256        string    `json:"sha256,omitempty"`
	ObjectKey     string    `json:"-"`
	Status        string    `json:"status"`
	Message       string    `json:"message,omitempty"`
	PolicyVersion string    `json:"-"`
	ObjectVersion int64     `json:"-"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type CreateInput struct {
	Principal      Principal
	ID             string
	Name           string
	MediaType      string
	Size           int64
	SHA256         string
	ObjectKey      string
	IdempotencyKey string
	RequestHash    string
	PolicyVersion  string
}
