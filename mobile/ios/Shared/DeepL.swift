import Foundation

enum TranslateError: Error {
    case auth(String)
    case quota(String)
    case failed(String)

    var message: String {
        switch self {
        case .auth(let m), .quota(let m), .failed(let m): return m
        }
    }
}

/// DeepL API (Free keys end in ":fx" and get 500,000 characters a month).
/// Calls are synchronous: the reader runs them on its own background queue.
final class DeepL {
    let key: String
    private let base: String
    private let session: URLSession

    init(key raw: String) throws {
        let key = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { throw TranslateError.auth("أدخل مفتاح DeepL في تطبيق PlayTranslate") }
        self.key = key
        base = key.hasSuffix(":fx") ? "https://api-free.deepl.com" : "https://api.deepl.com"
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 6
        config.timeoutIntervalForResource = 10
        config.httpAdditionalHeaders = ["Authorization": "DeepL-Auth-Key \(key)", "User-Agent": "PlayTranslate-iOS/0.1"]
        // One session keeps the TLS connection open between lines.
        session = URLSession(configuration: config)
    }

    deinit { session.finishTasksAndInvalidate() }

    private func perform(_ request: URLRequest) -> (Data?, Int, Error?) {
        let done = DispatchSemaphore(value: 0)
        var result: (Data?, Int, Error?) = (nil, 0, nil)
        session.dataTask(with: request) { data, response, error in
            result = (data, (response as? HTTPURLResponse)?.statusCode ?? 0, error)
            done.signal()
        }.resume()
        done.wait()
        return result
    }

    func translate(_ texts: [String], context: String = "") throws -> [String] {
        if texts.isEmpty { return [] }
        var payload: [String: Any] = ["text": texts, "source_lang": "EN", "target_lang": "AR",
                                      "tag_handling": "xml", "ignore_tags": ["x"], "preserve_formatting": true]
        // Context is not billed and helps with pronouns and short lines.
        if !context.isEmpty { payload["context"] = Glossary.escape(context) }
        var request = URLRequest(url: URL(string: base + "/v2/translate")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)

        var lastError = "تعذّر الاتصال بـ DeepL"
        for attempt in 0..<3 {
            let (data, status, error) = perform(request)
            if let error {
                lastError = "تعذّر الاتصال بـ DeepL (\(error.localizedDescription))"
                Thread.sleep(forTimeInterval: 0.3 * Double(attempt + 1))
                continue
            }
            switch status {
            case 200:
                guard let data,
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let items = obj["translations"] as? [[String: Any]] else {
                    throw TranslateError.failed("ردّ غير متوقع من DeepL")
                }
                let out = items.map { $0["text"] as? String ?? "" }
                guard out.count == texts.count else { throw TranslateError.failed("ردّ غير متوقع من DeepL") }
                return out
            case 403: throw TranslateError.auth("مفتاح DeepL غير صحيح")
            case 456: throw TranslateError.quota("انتهى رصيد DeepL المجاني لهذا الشهر")
            case 429, 500, 502, 503, 504:
                lastError = "DeepL مشغول (\(status))"
                Thread.sleep(forTimeInterval: 0.5 * Double(attempt + 1))
            default:
                throw TranslateError.failed("خطأ من DeepL (\(status))")
            }
        }
        throw TranslateError.failed(lastError)
    }

    /// (characters used, monthly limit).
    func usage() throws -> (Int, Int) {
        let (data, status, error) = perform(URLRequest(url: URL(string: base + "/v2/usage")!))
        if let error { throw TranslateError.failed("تعذّر الاتصال بـ DeepL (\(error.localizedDescription))") }
        if status == 403 { throw TranslateError.auth("مفتاح DeepL غير صحيح") }
        guard status == 200, let data,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw TranslateError.failed("خطأ من DeepL (\(status))")
        }
        return ((obj["character_count"] as? NSNumber)?.intValue ?? 0, (obj["character_limit"] as? NSNumber)?.intValue ?? 0)
    }
}
