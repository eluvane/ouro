# std/jsonrpc.ouro

JSON-RPC framing is byte-exact: Content-Length counts the body after the blank header line. Malformed envelopes decode to neutral fields so servers can still return protocol errors.

Declarations: 32.

## def rpc_crlf

```ouro
def rpc_crlf : String
```

## def rpc_header_end

```ouro
def rpc_header_end : String
```

## def rpc_len_key

```ouro
def rpc_len_key : String
```

## def rpc_frame

```ouro
def rpc_frame (body : String) : String
```

The space after the colon is what the base protocol specifies, and some clients match the header literally; on the way in rpc_content_len trims, so headers without it are still accepted.

## def rpc_send_json

```ouro
def rpc_send_json (j : Json) : String
```

## def rpc_content_len

```ouro
def rpc_content_len (header : String) : Maybe Nat
```

Content-Length from a header block, whichever line carries it.

## def rpc_take

```ouro
def rpc_take (buf : String) : Maybe (Pair String String)
```

First complete message and the unconsumed remainder.

## def json_pairs

```ouro
def json_pairs (j : Json) : List (Pair String Json)
```

Object fields and array elements of a value that may be neither.

## def json_obj_get

```ouro
def json_obj_get (j : Json) (k : String) : Maybe Json
```

Envelope accessors. A missing or mistyped field reads as the neutral value rather than failing, because a server must answer malformed input too.

## def json_items

```ouro
def json_items (j : Json) : List Json
```

## def json_str_or

```ouro
def json_str_or (j : Json) (d : String) : String
```

## def json_nat_or

```ouro
def json_nat_or (j : Json) (d : Nat) : Nat
```

## def json_field_str

```ouro
def json_field_str (j : Json) (k : String) (d : String) : String
```

## def json_field_nat

```ouro
def json_field_nat (j : Json) (k : String) (d : Nat) : Nat
```

## def json_field

```ouro
def json_field (j : Json) (k : String) : Json
```

## def json_num

```ouro
def json_num (n : Nat) : Json
```

## def rpc_method

```ouro
def rpc_method (msg : Json) : String
```

## def rpc_params

```ouro
def rpc_params (msg : Json) : Json
```

## def rpc_id

```ouro
def rpc_id (msg : Json) : Json
```

## def rpc_is_notification

```ouro
def rpc_is_notification (msg : Json) : Bool
```

A notification is a request without an id.

## def rpc_obj

```ouro
def rpc_obj (fields : List (Pair String Json)) : Json
```

## def rpc_version_field

```ouro
def rpc_version_field : Pair String Json
```

## def rpc_result

```ouro
def rpc_result (id : Json) (result : Json) : Json
```

## def rpc_error_obj

```ouro
def rpc_error_obj (code : Json) (msg : String) : Json
```

## def rpc_error

```ouro
def rpc_error (id : Json) (code : Json) (msg : String) : Json
```

## def rpc_notify

```ouro
def rpc_notify (method : String) (params : Json) : Json
```

## def rpc_request

```ouro
def rpc_request (id : Json) (method : String) (params : Json) : Json
```

## def rpc_err_parse

```ouro
def rpc_err_parse : Json
```

Standard JSON-RPC error codes (LSP uses the same numbers). They are negative and Nat is not, so they stay JSON numbers written out in full.

## def rpc_err_invalid_request

```ouro
def rpc_err_invalid_request : Json
```

## def rpc_err_method_not_found

```ouro
def rpc_err_method_not_found : Json
```

## def rpc_err_invalid_params

```ouro
def rpc_err_invalid_params : Json
```

## def rpc_err_internal

```ouro
def rpc_err_internal : Json
```
