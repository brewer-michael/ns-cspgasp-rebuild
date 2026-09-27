# Home Assistant

- **ESP32-S3 brain:** [ESP32-S3 speaker](#esp32-s3-speaker), just below.
- **Raspberry Pi brain:** [Raspberry Pi speaker](#raspberry-pi-speaker).

The Assist pipeline, which picks the speech and language servers, is the same for
both: [2. An Assist pipeline on your own network](#2-an-assist-pipeline-on-your-own-network).

## ESP32-S3 speaker

The ESP32-S3 build is an ESPHome device, so Home Assistant sets it up like any
other.

1. Flash it: [esphome/README.md](../esphome/README.md#install).
2. Home Assistant discovers it. Add it under **Settings → Devices & services**,
   with the API encryption key from its YAML.
3. Create an Assist pipeline ([below](#2-an-assist-pipeline-on-your-own-network))
   and choose it on the speaker's device page.
4. For the temperature on the clock, set `temperature_entity` in its YAML
   ([settings](../esphome/README.md#settings)).
5. Expose the entities you want to control under **Settings → Voice assistants →
   Expose**.

Its media player takes announcements like any other:

```yaml
action: tts.speak
target:
  entity_id: tts.piper
data:
  media_player_entity_id: media_player.open_speaker   # your speaker's media player
  message: "The washing machine is done."
```

The alarm clock is on the device page (**Alarm**, **Alarm time**, **Alarm days**).
An automation can set it, or ring the speaker with the
`esphome.open_speaker_ring_alarm` action (named after the speaker's `name`).
Timers set by voice ring on the speaker.

The rest of this page is about the Raspberry Pi build.

## Raspberry Pi speaker

Open Speaker works with Home Assistant in two ways. Pick one with `pipeline.mode`
in `/etc/open-speaker/config.yaml`.

| | `homeassistant` (default) | `local` |
|---|---|---|
| Speech-to-text, language model, text-to-speech | An Assist pipeline in Home Assistant | Your own servers, called directly by the speaker ([LOCAL_AI.md](LOCAL_AI.md)) |
| Controlling devices | Home Assistant's agent (built in, or an LLM such as Ollama) | The `homeassistant` agent in the agent chain |
| Home Assistant needed | Yes | Optional |

In both modes the speaker handles timers, alarms, stop, snooze and volume itself,
so these keep working when Home Assistant or a server is down
(`pipeline.local_intents`).

The speaker uses Home Assistant's WebSocket and REST APIs with an access token.
You don't need a custom integration, and it doesn't appear as a device in Home
Assistant. Automations talk to it over its own small HTTP API (below).

## 1. Access token

1. In Home Assistant open your profile, then **Security**, then **Long-lived
   access tokens**, and create a token called `Open Speaker`.
2. On the speaker, put it in the secrets file:

   ```sh
   sudoedit /etc/open-speaker/secrets.env      # HA_TOKEN=eyJ...
   ```

3. Set the address in `/etc/open-speaker/config.yaml`:

   ```yaml
   homeassistant:
     url: http://homeassistant.local:8123
     token: ${HA_TOKEN}
   ```

4. Check it: `sudo open-speaker doctor` connects, authenticates and lists your
   Assist pipelines.

## 2. An Assist pipeline on your own network

Under **Settings → Voice assistants**, create a pipeline (or edit the default):

- **Speech-to-text**: Whisper or Speech-to-Phrase. Install the add-on, or run the
  server from [`server/docker-compose.yml`](../server/docker-compose.yml) and add
  it with **Settings → Devices & services → Add integration → Wyoming Protocol**
  (host of your server, port 10300).
- **Conversation agent**: *Home Assistant* for device control. Or add the
  **Ollama** integration (port 11434), allow it to control Home Assistant, and
  turn on *Prefer handling commands locally*. Common commands then skip the
  language model and stay fast.
- **Text-to-speech**: Piper (add-on, or Wyoming Protocol on port 10200).

The speaker uses your preferred pipeline. To use a different one, set its id:

```yaml
homeassistant:
  pipeline: 01jabcdefghijk      # "sudo open-speaker doctor" lists the ids
```

Expose the entities you want to control under **Settings → Voice assistants →
Expose**.

## 3. Temperature on the display

The display shows the time and a temperature, like the original. Use any
temperature sensor or weather entity:

```yaml
display:
  temperature:
    entity: weather.forecast_home        # or sensor.outdoor_temperature
```

## 4. Automations: announcements, timers, alarms

The speaker listens on port 10800. Set `api.token` (e.g. `${API_TOKEN}` from the
secrets file) if other people use your network, and send it as a bearer token.

| Method and path | Body | Does |
|---|---|---|
| `POST /api/say` | `{"text": "..."}` | Speaks the text, ducking any music |
| `POST /api/play` | `{"url": "http://..."}` | Plays a sound or media URL (MP3, WAV, ...) |
| `POST /api/listen` | | Starts listening, like the action button |
| `POST /api/stop` | | Stops speech, playback and ringing |
| `POST /api/volume` | `{"level": 40}` or `{"steps": -2}` | Sets the volume (0–100) |
| `POST /api/mute` | `{"microphone": true}`, `{"speaker": false}` | Mutes or unmutes |
| `GET /api/status` | | State, volume, mute, ringing, temperature, timers, alarms |
| `GET/POST/DELETE /api/timers` | `{"seconds": 300, "name": "tea"}` | Lists, starts or cancels (`?name=tea`) timers |
| `GET/POST/DELETE /api/alarms` | `{"time": "06:30", "repeat": "weekdays"}` | Lists, sets or cancels (`?time=06:30`) alarms |

`repeat` can be `daily`, `weekdays`, `weekends` or a list of days such as
`["mon", "wed", "fri"]`. Leave it out for a one-off alarm.

### Announcements

`configuration.yaml`:

```yaml
rest_command:
  speaker_say:
    url: http://open-speaker.local:10800/api/say
    method: POST
    headers:
      Authorization: !secret open_speaker_auth     # "Bearer <API_TOKEN>"
    content_type: application/json
    payload: '{"text": {{ message | tojson }}}'
  speaker_alarm:
    url: http://open-speaker.local:10800/api/alarms
    method: POST
    headers:
      Authorization: !secret open_speaker_auth
    content_type: application/json
    payload: '{"time": "{{ time }}", "repeat": "{{ repeat | default("") }}"}'
```

An automation:

```yaml
automation:
  - alias: Announce the washer
    triggers:
      - trigger: state
        entity_id: sensor.washer_status
        to: finished
    actions:
      - action: rest_command.speaker_say
        data:
          message: The washing is done.
```

### The speaker's state in Home Assistant

```yaml
rest:
  - resource: http://open-speaker.local:10800/api/status
    headers:
      Authorization: !secret open_speaker_auth
    scan_interval: 10
    sensor:
      - name: Speaker state
        value_template: "{{ value_json.state }}"
      - name: Speaker next alarm
        value_template: "{{ value_json.alarms | map(attribute='next') | sort | first | default('none') }}"
    binary_sensor:
      - name: Speaker ringing
        value_template: "{{ value_json.ringing | count > 0 }}"
```

With these you can, for example, turn the bedroom lights on slowly when the alarm
rings.

## 5. Music (optional)

The speaker doesn't include a music player. For Spotify Connect, install
[raspotify](https://github.com/dtcooper/raspotify) and set its output device to
`music` (`LIBRESPOT_DEVICE=music` in `/etc/raspotify/conf`). That device has its
own volume control, and the speaker turns it down while it talks:

```yaml
audio:
  output:
    duck_control: Music
```
