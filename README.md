# Breath of Life

Contactless breathing observation with two low-cost ESP32 boards and Wi-Fi Channel State Information. Built at Hack the Valley.

[![Watch the Breath of Life demo](https://img.youtube.com/vi/qeF7PjO_inE/maxresdefault.jpg)](https://youtu.be/qeF7PjO_inE)

[Watch the demo on YouTube](https://youtu.be/qeF7PjO_inE)

## Inspiration

We wanted to explore a simple question: could two low-cost Wi-Fi boards help someone notice a change in breathing without asking the person to wear a sensor?

In a waiting area or care setting, a person may need attention before they can ask for it. We started Breath of Life to investigate whether small changes in wireless signals could make breathing patterns visible to a caregiver. Our focus is a seated, single-person prototype that we can test and improve.

## What it does and how we built it

![Breath of Life tech stack](frontend/public/BOF%20-%20Tech%20Stack.png)

Breath of Life captures changes in a Wi-Fi channel and gives us tools to inspect them for breathing-related patterns. We use two ESP32 boards: a transmitter sends ESP-NOW packets, and a receiver captures Channel State Information (CSI) and streams it to a laptop over USB. We build on Espressif's open-source ESP-CSI examples.

Our Python reader parses the receiver's CSI packets, validates the I/Q arrays, preserves timestamps, and marks invalid samples. It also reports packet rates, malformed records, and missing packet IDs. We can save the original serial output as JSONL or use our Parquet recorder for analysis.

For placement and debugging, we built a live desktop view with a subcarrier-amplitude heatmap and a smoothed common waveform. For saved recordings, our analysis script removes outliers with a median filter, compares raw and gain-normalized amplitudes, resamples the signal, and applies Butterworth filters. Principal component analysis and Welch power spectra help us inspect candidate breathing rhythms and estimate their dominant frequency.

The current build provides acquisition, visualization, and exploratory breathing analysis. We are still testing how reliably those patterns distinguish breathing from other movement.

## Why it matters

We want to make contactless breathing observation more accessible using inexpensive hardware. A future care-team interface could help someone notice a sustained change and decide to check on the person. Our prototype explores that possibility without collecting camera images or requiring a worn device.

We are building an experimental sensing tool. Clinical reliability and usefulness still require validation.

## Challenges we ran into

Getting numbers from the receiver was only the first step. We had to handle quoted CSI arrays, incomplete serial lines, different packet lengths, invalid initial samples, and a device clock that wraps. We also learned that two programs competing for one serial port can leave a graph flat even while the boards communicate.

The harder signal problem is separating breathing-related changes from body movement, receiver gain changes, and the surrounding wireless environment. We added recordings, packet diagnostics, and comparisons between raw and normalized signals so we could investigate those effects instead of trusting a smooth-looking curve.

## Accomplishments that we're proud of

We established the ESP32 wireless link, captured real CSI packets, and built a reader that continues through malformed input. We can inspect live channel changes and analyze saved recordings through the same development workflow.

We also checked the software against real captured packet examples and a virtual serial port. Our combined reader and backend suite passes 40 tests, covering parsing, timing, recording, and failure handling. Those checks give us a foundation for the next round of hardware trials.

## What we learned

We learned how wireless channel measurements represent complex I/Q values and why packet timing matters for signal processing. We also learned to separate acquisition, analysis, and visualization so teammates could develop and debug each part.

Most of all, we learned to distinguish a visible periodic pattern from evidence of reliable breathing detection. Recording the raw data and checking assumptions became as important as plotting the result.

## What's next for Breath of Life

Our next milestone is to compare empty-chair, normal-breathing, and movement recordings across board placements. From those results, we plan to build a continuous pipeline with breathing, movement, pause, and unavailable-signal states.

We then want to stream processed results through a FastAPI WebSocket server to a phone-friendly dashboard. A user-enabled phone alarm could flag a sustained pause for someone to check, with signal-quality checks to reduce misleading alerts. We will keep testing across environments before making reliability claims.

## Running it

Board setup, recording, analysis, the live dashboard, and the phone alarm are covered in the [developer guide](docs/DEVELOPMENT.md).