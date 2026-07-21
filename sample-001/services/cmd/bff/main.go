package main

import (
	"example.com/sample-001/services/internal/launch"
	"log"
)

func main() {
	if err := launch.BFF(); err != nil {
		log.Fatal(err)
	}
}
