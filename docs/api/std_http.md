# std/http.ouro

HTTP message codec and native Windows WinHTTP POST transport. Transport failures have status zero and an explicit reason. HTTP errors retain their actual status and binary response body; response headers are not collected by this transport. TLS certificate verification is OS-owned.

Declarations: 27.

## intrinsic prim_http_request

```
intrinsic prim_http_request : String -> List (Pair String String) -> String -> IO (Pair Nat (Pair String String))
```

The checked native action returns the HTTP status, exact response bytes, and transport failure reason. Status zero denotes a transport failure.

## def crlf

```
def crlf : String
```

## def n200

```
def n200 : Nat
```

## def n300

```
def n300 : Nat
```

## inductive HttpReq

```
inductive HttpReq : Type
```

## inductive HttpResp

```
inductive HttpResp : Type
```

## def http_method

```
def http_method (r : HttpReq) : String
```

## def http_target

```
def http_target (r : HttpReq) : String
```

## def http_req_headers

```
def http_req_headers (r : HttpReq) : List (Pair String String)
```

## def http_req_body

```
def http_req_body (r : HttpReq) : String
```

## def http_status

```
def http_status (r : HttpResp) : Nat
```

## def http_reason

```
def http_reason (r : HttpResp) : String
```

## def http_resp_headers

```
def http_resp_headers (r : HttpResp) : List (Pair String String)
```

## def http_body

```
def http_body (r : HttpResp) : String
```

## def http_ok

```
def http_ok (r : HttpResp) : Bool
```

## def header_ok

```
def header_ok (s : String) : Bool
```

## def header_line

```
def header_line (p : Pair String String) : String
```

## def render_headers

```
def render_headers (hs : List (Pair String String)) : String
```

## def render_request

```
def render_request (r : HttpReq) : String
```

## def parse_header

```
def parse_header (line : String) : Maybe (Pair String String)
```

## def parse_headers

```
def parse_headers : List String -> Maybe (List (Pair String String))
```

## def parse_status_line

```
def parse_status_line (line : String) : Maybe (Pair Nat String)
```

## def split_http_lines

```
def split_http_lines (s : String) : List String
```

## def parse_response_parts

```
def parse_response_parts (head : String) (body : String) : HttpResp
```

## def parse_response

```
def parse_response (raw : String) : HttpResp
```

## def http_fail

```
def http_fail (msg : String) : HttpResp
```

## def http_post

```
def http_post (url : String) (headers : List (Pair String String))
```
