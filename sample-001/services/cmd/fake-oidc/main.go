package main

import (
	"log"

	"example.com/sample-001/services/internal/launch"
)

func main() {
	if err := launch.FakeOIDC(); err != nil {
		log.Fatal(err)
	}
}
