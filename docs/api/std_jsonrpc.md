# std/jsonrpc.ouro

JSON-RPC framing is byte-exact: Content-Length counts the body after the blank header line. Malformed envelopes decode to neutral fields so servers can still return protocol errors.

Declarations: 32.

## def rpc_crlf

```
def rpc_crlf : String
```

## def rpc_header_end

```
def rpc_header_end : String
```

## def rpc_len_key

```
def rpc_len_key : String
```

## def rpc_frame

```
def rpc_frame (body : String) : String
```

The space after the colon is what the base protocol specifies, and some clients match the header literally; on the way in rpc_content_len trims, so headers without it are still accepted.

## def rpc_send_json

```
def rpc_send_json (j : Json) : String
```

## def rpc_content_len

```
def rpc_content_len (header : String) : Maybe Nat
```

Content-Length from a header block, whichever line carries it.

## def rpc_take

```
def rpc_take (buf : String) : Maybe (Pair String String)
```

First complete message and the unconsumed remainder.

## def json_pairs

```
def json_pairs (j : Json) : List (Pair String Json)
```

Object fields and array elements of a value that may be neither.

## def json_obj_get

```
def json_obj_get (j : Json) (k : String) : Maybe Json
```

Envelope accessors. A missing or mistyped field reads as the neutral value rather than failing, because a server must answer malformed input too.

## def json_items

```
def json_items (j : Json) : List Json
```

## def json_str_or

```
def json_str_or (j : Json) (d : String) : String
```

## def json_nat_or

```
def json_nat_or (j : Json) (d : Nat) : Nat
```

## def json_field_str

```
def json_field_str (j : Json) (k : String) (d : String) : String
```

## def json_field_nat

```
def json_field_nat (j : Json) (k : String) (d : Nat) : Nat
```

## def json_field

```
def json_field (j : Json) (k : String) : Json
```

## def json_num

```
def json_num (n : Nat) : Json
```

## def rpc_method

```
def rpc_method (msg : Json) : String
```

## def rpc_params

```
def rpc_params (msg : Json) : Json
```

## def rpc_id

```
def rpc_id (msg : Json) : Json
```

## def rpc_is_notification

```
def rpc_is_notification (msg : Json) : Bool
```

A notification is a request without an id.

## def rpc_obj

```
def rpc_obj (fields : List (Pair String Json)) : Json
```

## def rpc_version_field

```
def rpc_version_field : Pair String Json
```

## def rpc_result

```
def rpc_result (id : Json) (result : Json) : Json
```

## def rpc_error_obj

```
def rpc_error_obj (code : Json) (msg : String) : Json
```

## def rpc_error

```
def rpc_error (id : Json) (code : Json) (msg : String) : Json
```

## def rpc_notify

```
def rpc_notify (method : String) (params : Json) : Json
```

## def rpc_request

```
def rpc_request (id : Json) (method : String) (params : Json) : Json
```

## def rpc_err_parse

```
def rpc_err_parse : Json
```

Standard JSON-RPC error codes (LSP uses the same numbers). They are negative and Nat is not, so they stay JSON numbers written out in full.

## def rpc_err_invalid_request

```
def rpc_err_invalid_request : Json
```

## def rpc_err_method_not_found

```
def rpc_err_method_not_found : Json
```

## def rpc_err_invalid_params

```
def rpc_err_invalid_params : Json
```

## def rpc_err_internal

```
def rpc_err_internal : Json
```
